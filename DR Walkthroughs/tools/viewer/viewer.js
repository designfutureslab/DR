/* Grasshopper walkthrough viewer.
 * Draws a Grasshopper canvas (from the JSON model built by tools/build.py) as SVG,
 * with numbered pins for the current walkthrough step and an inspector for any object.
 * Everything it needs is in window.WT. */
(function () {
  'use strict';
  const WT = window.WT;
  const M = WT.model;
  const NS = 'http://www.w3.org/2000/svg';
  const $ = (s) => document.querySelector(s);
  const esc = (s) => String(s == null ? '' : s).replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));

  const steps = [];
  WT.parts.forEach((p, pi) => p.steps.forEach((s) => { s.part = pi; s.index = steps.length; steps.push(s); }));

  const state = { mode: 'walk', step: 0, doc: null, k: 1, tx: 0, ty: 0, sel: null, inspecting: false };
  const wrap = $('#wrap'), svg = $('#cv'), pinsEl = $('#pins'), tip = $('#tip'), notes = $('#notes');
  let world, idx = {};   // idx: per-rendered-doc lookup tables

  // ------------------------------------------------------------------ helpers
  const rgba = (c, fallback) => c ? `rgba(${c.r},${c.g},${c.b},${(c.a / 255).toFixed(3)})` : fallback;
  const rgb = (c) => `rgb(${c.r},${c.g},${c.b})`;
  function el(tag, attrs, parent) {
    const e = document.createElementNS(NS, tag);
    for (const k in attrs) if (attrs[k] != null) e.setAttribute(k, attrs[k]);
    if (parent) parent.appendChild(e);
    return e;
  }
  function txt(parent, x, y, s, attrs) {
    const t = el('text', Object.assign({ x, y }, attrs || {}), parent);
    t.textContent = s;
    return t;
  }
  const libName = (o) => (o.lib && M.libraries[o.lib] ? M.libraries[o.lib].name : 'Grasshopper');
  const docTitle = (did) => {
    const p = WT.doc_path[did];
    return p === '' || p == null ? 'Main canvas' : p.split('/').pop();
  };
  const objName = (o) => (o.nick && o.nick.trim()) || o.name || o.type;
  const fit1 = (s, n) => (s.length > n ? s.slice(0, Math.max(1, n - 1)) + '…' : s);

  // ------------------------------------------------------------------ rendering
  function render(did) {
    state.doc = did;
    state.view = 'canvas';
    const d = M.docs[did];
    svg.innerHTML = '';
    const defs = el('defs', {}, svg);
    const pat = el('pattern', { id: 'grid', width: 100, height: 100, patternUnits: 'userSpaceOnUse' }, defs);
    el('path', { d: 'M100 0H0V100', fill: 'none', stroke: 'var(--cv-grid)', 'stroke-width': 1 }, pat);
    world = el('g', { id: 'world' }, svg);
    const b = d.bounds || [0, 0, 100, 100];
    el('rect', { x: b[0] - 20000, y: b[1] - 20000, width: b[2] + 40000, height: b[3] + 40000, fill: 'url(#grid)' }, world);
    const gG = el('g', { class: 'groups' }, world);
    const gW = el('g', { class: 'wires' }, world);
    const gO = el('g', { class: 'objs' }, world);
    const gL = el('g', { class: 'labels' }, world);
    const gF = el('g', { class: 'focus' }, world);

    idx = { obj: {}, param: {}, node: {}, grp: {}, wiresOf: {}, gfocus: gF, groupsById: {} };
    d.objects.forEach((o) => {
      idx.obj[o.id] = o;
      (o.inputs || []).forEach((p) => (idx.param[p.id] = { o, p, side: 'in' }));
      (o.outputs || []).forEach((p) => (idx.param[p.id] = { o, p, side: 'out' }));
    });
    d.groups.forEach((g) => (idx.groupsById[g.id] = g));

    // groups: biggest first so nested groups sit on top
    const groups = d.groups.filter((g) => g.bounds && !g.label_only && g.member_objects.length + g.member_groups.length > 0);
    groups.sort((a, b2) => b2.bounds[2] * b2.bounds[3] - a.bounds[2] * a.bounds[3]);
    groups.forEach((g) => drawGroup(g, gG));

    // wires
    d.wires.forEach((w, i) => {
      const a = anchor(w.from, w.from_param, 'out'), z = anchor(w.to, w.to_param, 'in');
      if (!a || !z) return;
      const dx = Math.max(24, Math.abs(z[0] - a[0]) * 0.5);
      const cls = 'wire' + (w.display === 1 ? ' faint' : w.display === 2 ? ' hidden' : '');
      const p = el('path', { class: cls, d: `M${a[0]},${a[1]} C${a[0] + dx},${a[1]} ${z[0] - dx},${z[1]} ${z[0]},${z[1]}` }, gW);
      p.dataset.from = w.from; p.dataset.to = w.to;
      (idx.wiresOf[w.from] = idx.wiresOf[w.from] || []).push(p);
      (idx.wiresOf[w.to] = idx.wiresOf[w.to] || []).push(p);
    });

    // objects
    d.objects.forEach((o) => { if (o.bounds) drawObject(o, gO); });

    // Bifocals-style name tags (invisible single-object groups used as labels)
    d.groups.forEach((g) => {
      if (!g.label_only || g.member_objects.length !== 1 || !g.nick) return;
      const o = idx.obj[g.member_objects[0]];
      if (!o || !o.bounds) return;
      const t = g.nick.trim(), w = t.length * 3.9 + 8;
      const lg = el('g', { class: 'bifocal' }, gL);
      el('rect', { x: o.bounds[0], y: o.bounds[1] - 13, width: w, height: 10.5, rx: 1.5 }, lg);
      txt(lg, o.bounds[0] + 4, o.bounds[1] - 5.3, t);
    });
    applyLOD();
  }

  function anchor(oid, pid, side) {
    const o = idx.obj[oid];
    if (!o || !o.bounds) return null;
    if (pid && idx.param[pid] && idx.param[pid].p.bounds) {
      const b = idx.param[pid].p.bounds;
      return side === 'out' ? [o.bounds[0] + o.bounds[2], b[1] + b[3] / 2] : [o.bounds[0], b[1] + b[3] / 2];
    }
    const b = o.bounds;
    return side === 'out' ? [b[0] + b[2], b[1] + b[3] / 2] : [b[0], b[1] + b[3] / 2];
  }

  function groupObjectBounds(g, seen) {
    seen = seen || {};
    if (seen[g.id]) return [];
    seen[g.id] = 1;
    let out = g.member_objects.map((id) => idx.obj[id]).filter((o) => o && o.bounds).map((o) => o.bounds);
    g.member_groups.forEach((gid) => { if (idx.groupsById[gid]) out = out.concat(groupObjectBounds(idx.groupsById[gid], seen)); });
    return out;
  }

  function drawGroup(g, parent) {
    const c = g.colour || { r: 150, g: 150, b: 150, a: 60 };
    const G = el('g', { class: 'grp', 'data-id': g.id }, parent);
    const fill = el('g', { class: 'gfill', opacity: Math.max(0.12, c.a / 255).toFixed(3) }, G);
    const pad = 7;
    if (g.border === 5) {
      groupObjectBounds(g).forEach((b) => el('rect', { x: b[0] - pad, y: b[1] - pad, width: b[2] + pad * 2, height: b[3] + pad * 2, rx: 9, fill: rgb(c) }, fill));
    } else {
      const b = g.bounds;
      el('rect', { x: b[0] - pad, y: b[1] - pad, width: b[2] + pad * 2, height: b[3] + pad * 2, rx: 4, fill: rgb(c) }, fill);
    }
    if (g.nick && g.nick.trim()) {
      const t = g.nick.trim();
      const lg = el('g', { class: 'bifocal' }, G);
      el('rect', { x: g.bounds[0] - pad, y: g.bounds[1] - pad - 13, width: t.length * 5 + 10, height: 12, rx: 2 }, lg);
      txt(lg, g.bounds[0] - pad + 5, g.bounds[1] - pad - 4, t, { class: 'grp-label', style: 'font-size:8.5px' });
    }
    idx.grp[g.id] = G;
  }

  function drawObject(o, parent) {
    const [x, y, w, h] = o.bounds;
    const G = el('g', { class: 'ob k-' + o.kind, 'data-id': o.id }, parent);
    idx.node[o.id] = G;
    const k = o.kind;
    const body = (fill, rx) => el('rect', { class: 'body', x, y, width: w, height: h, rx: rx == null ? 3 : rx, style: fill ? 'fill:' + fill : null }, G);

    if (k === 'component' || k === 'cluster' || k === 'script') {
      body(null, 4);
      const ins = (o.inputs || []).filter((p) => p.bounds), outs = (o.outputs || []).filter((p) => p.bounds);
      let sx0 = x + 3, sx1 = x + w - 3;
      if (ins.length) sx0 = Math.max(...ins.map((p) => p.bounds[0] + p.bounds[2]));
      if (outs.length) sx1 = Math.min(...outs.map((p) => p.bounds[0]));
      ins.forEach((p) => {
        const b = p.bounds, cy = b[1] + b[3] / 2;
        txt(G, b[0] + 3, cy + 2.7, fit1((p.nick || p.name || '').trim(), Math.floor(b[2] / 4.1)), { class: 'pn' });
        el('circle', { class: 'grip', cx: x, cy, r: 2.6 }, G);
      });
      outs.forEach((p) => {
        const b = p.bounds, cy = b[1] + b[3] / 2;
        txt(G, b[0] + b[2] - 3, cy + 2.7, fit1((p.nick || p.name || '').trim(), Math.floor(b[2] / 4.1)), { class: 'pn', 'text-anchor': 'end' });
        el('circle', { class: 'grip', cx: x + w, cy, r: 2.6 }, G);
      });
      if (sx1 - sx0 > 7) {
        el('rect', { class: 'strip', x: sx0 + 1, y: y + 2, width: sx1 - sx0 - 2, height: h - 4, rx: 2 }, G);
        const cx = (sx0 + sx1) / 2, cy = y + h / 2;
        txt(G, cx, cy + 3, fit1(objName(o), Math.floor((h - 6) / 5)), { class: 'strip-t', 'text-anchor': 'middle', transform: `rotate(-90 ${cx} ${cy})` });
      }
      return;
    }
    if (k === 'panel') {
      const col = o.colour ? rgba(Object.assign({}, o.colour, { a: Math.max(o.colour.a, 200) })) : 'rgb(255,250,90)';
      el('rect', { class: 'body panel-body', x, y, width: w, height: h, rx: 1, style: 'fill:' + col }, G);
      let top = y;
      const nick = (o.nick || '').trim();
      if (nick && nick !== 'Panel') {
        el('rect', { class: 'panel-head', x, y, width: w, height: 11 }, G);
        txt(G, x + w / 2, y + 8, fit1(nick, Math.floor(w / 4.3)), { class: 'lab', 'text-anchor': 'middle', style: 'font-weight:600;font-size:7.5px' });
        top = y + 11;
      }
      if (h - (top - y) > 6) {
        const fo = el('foreignObject', { x, y: top, width: w, height: h - (top - y) }, G);
        const div = document.createElement('div');
        const live = o.sources && o.sources.length;
        div.className = 'ptext' + (live ? ' live' : '');
        div.textContent = live ? 'live output' : (o.text || '');
        fo.appendChild(div);
      }
      el('circle', { class: 'grip', cx: x, cy: y + h / 2, r: 2.6 }, G);
      el('circle', { class: 'grip', cx: x + w, cy: y + h / 2, r: 2.6 }, G);
      return;
    }
    if (k === 'scribble') {
      const size = o.size || 20;
      const t = el('text', { class: 'scrib', x: x + 5, y: y + size * 0.92, style: `font-size:${size * 0.9}px` }, G);
      String(o.text || '').split('\n').forEach((line, i) => {
        const ts = el('tspan', { x: x + 5, dy: i ? size * 1.1 : 0 }, t);
        ts.textContent = line;
      });
      return;
    }
    if (k === 'slider') {
      body(null, 5);
      const name = (o.nick || '').trim();
      const labW = name ? Math.min(w * 0.45, name.length * 4.3 + 10) : 6;
      if (name) {
        el('rect', { x: x + 1.5, y: y + 1.5, width: labW, height: h - 3, rx: 3, fill: '#b9b9b9' }, G);
        txt(G, x + 5, y + h / 2 + 3, name, { class: 'lab' });
      }
      const t0 = x + labW + 8, t1 = x + w - 8;
      el('line', { class: 'track', x1: t0, y1: y + h / 2, x2: t1, y2: y + h / 2 }, G);
      const f = o.max > o.min ? (o.val - o.min) / (o.max - o.min) : 0;
      const kx = t0 + (t1 - t0) * Math.min(1, Math.max(0, f));
      el('rect', { class: 'knob', x: kx - 3, y: y + 3, width: 6, height: h - 6, rx: 1.5 }, G);
      const vs = Number(o.val).toFixed(o.digits == null ? 2 : o.digits);
      txt(G, kx + (f > 0.7 ? -6 : 6), y + h / 2 + 2.8, vs, { class: 'val', 'text-anchor': f > 0.7 ? 'end' : 'start' });
      el('circle', { class: 'grip', cx: x + w, cy: y + h / 2, r: 2.6 }, G);
      return;
    }
    if (k === 'valuelist') {
      body(null, 4);
      const sel = (o.options || []).filter((q) => q.selected).map((q) => q.name).join(', ') || '(none)';
      el('rect', { x: x + 3, y: y + 3, width: w - 20, height: h - 6, rx: 2, fill: '#f1f1f1', stroke: '#8a8a8a', 'stroke-width': 0.6 }, G);
      txt(G, x + 7, y + h / 2 + 3, fit1(sel, Math.floor((w - 26) / 4.2)), { class: 'lab' });
      el('path', { d: `M${x + w - 13},${y + h / 2 - 2} l4,5 l4,-5 z`, fill: '#333' }, G);
      el('circle', { class: 'grip', cx: x + w, cy: y + h / 2, r: 2.6 }, G);
      return;
    }
    if (k === 'toggle' || k === 'button') {
      body(null, 4);
      const name = (o.nick || '').trim();
      txt(G, x + 6, y + h / 2 + 3, fit1(name, Math.floor((w - 40) / 4.3)), { class: 'lab' });
      if (k === 'toggle') {
        el('rect', { class: o.val ? 'yes' : 'no', x: x + w - 34, y: y + 3, width: 30, height: h - 6, rx: 2 }, G);
        txt(G, x + w - 19, y + h / 2 + 3, o.val ? 'True' : 'False', { class: 'lab', 'text-anchor': 'middle', style: 'fill:#fff;font-weight:600' });
      } else {
        el('rect', { x: x + w - 22, y: y + 3, width: 18, height: h - 6, rx: 2, fill: '#6f7478' }, G);
        el('path', { d: `M${x + w - 16},${y + h / 2 - 4} l6,4 l-6,4 z`, fill: '#fff' }, G);
      }
      el('circle', { class: 'grip', cx: x + w, cy: y + h / 2, r: 2.6 }, G);
      return;
    }
    if (k === 'swatch') {
      body(null, 4);
      el('rect', { x: x + 3, y: y + 3, width: w - 6, height: h - 6, rx: 2, fill: o.colour ? rgb(o.colour) : '#888', stroke: '#444', 'stroke-width': 0.5 }, G);
      el('circle', { class: 'grip', cx: x + w, cy: y + h / 2, r: 2.6 }, G);
      return;
    }
    // floating params, cluster hooks, relays
    body(null, k === 'relay' ? h / 2 : 3);
    let label = (o.nick || '').trim() || o.name || '';
    if (k === 'cluster_input') label = '▸ ' + label;
    if (k === 'cluster_output') label = label + ' ▸';
    if (k !== 'relay') txt(G, x + w / 2, y + h / 2 + 3, fit1(label, Math.floor((w - 6) / 4.2)), { class: 'lab', 'text-anchor': 'middle' });
    el('circle', { class: 'grip', cx: x, cy: y + h / 2, r: 2.6 }, G);
    el('circle', { class: 'grip', cx: x + w, cy: y + h / 2, r: 2.6 }, G);
  }

  // ------------------------------------------------------------------ stage map
  function stageSummary(st) {
    return (st.summary || '').replace(/\s+/g, ' ').trim();
  }
  function renderMap(active) {
    const SM = WT.stage_map, S = SM.stages;
    state.view = 'map'; state.doc = null;
    svg.innerHTML = '';
    const defs = el('defs', {}, svg);
    const mk = el('marker', { id: 'arrowhead', viewBox: '0 0 10 10', refX: 8, refY: 5, markerWidth: 7, markerHeight: 7, orient: 'auto-start-reverse' }, defs);
    el('path', { d: 'M0,0 L10,5 L0,10 z', class: 'arrow-tip' }, mk);
    world = el('g', { id: 'world' }, svg);
    idx = { obj: {}, param: {}, node: {}, grp: {}, wiresOf: {}, groupsById: {}, gfocus: el('g', {}, world) };
    pinsEl.innerHTML = ''; curPins = [];
    // rows = data-flow order (top to bottom); stages in a row sorted by canvas position
    const W = 210, H = 58, GX = 34, GY = 96;
    const rows = {};
    S.forEach((st, i) => (rows[st.rank] = rows[st.rank] || []).push(i));
    const ranks = Object.keys(rows).map(Number).sort((a, b) => a - b);
    const widest = Math.max(...ranks.map((r) => rows[r].length));
    const fullW = widest * W + (widest - 1) * GX;
    const pos = {};
    ranks.forEach((r, ri) => {
      rows[r].sort((a, b) => (S[a].x || 0) - (S[b].x || 0) || S[a].y - S[b].y || a - b);
      const rw = rows[r].length * W + (rows[r].length - 1) * GX;
      rows[r].forEach((i, k) => { pos[i] = { x: (fullW - rw) / 2 + k * (W + GX), y: ri * (H + GY), w: W, h: H }; });
    });
    const fwd = SM.flows.map((f, fi) => fi).filter((fi) => !SM.flows[fi].feedback);
    const outs = {}, ins = {};
    fwd.forEach((fi) => { const f = SM.flows[fi]; (outs[f.from] = outs[f.from] || []).push(fi); (ins[f.to] = ins[f.to] || []).push(fi); });
    const portX = (list, i, fi, key) => {
      const arr = list[i].slice().sort((a, b) => pos[SM.flows[a][key]].x - pos[SM.flows[b][key]].x);
      const k = arr.indexOf(fi);
      return pos[i].x + pos[i].w * (k + 1) / (arr.length + 1);
    };
    const gA = el('g', { class: 'map-flows' }, world);
    const gL = el('g', { class: 'map-labels' }, world);
    const gB = el('g', { class: 'map-blocks' }, world);
    const arrows = {};
    let skips = 0;
    const track = (f, g) => { (arrows[f.from] = arrows[f.from] || []).push(g); (arrows[f.to] = arrows[f.to] || []).push(g); };
    fwd.forEach((fi) => {
      const f = SM.flows[fi], a = pos[f.from], b = pos[f.to];
      const x1 = portX(outs, f.from, fi, 'to'), y1 = a.y + a.h, x2 = portX(ins, f.to, fi, 'from'), y2 = b.y;
      const g = el('g', { class: 'flow' }, gA);
      const rowsApart = ranks.indexOf(S[f.to].rank) - ranks.indexOf(S[f.from].rank);
      let d;
      if (rowsApart > 1) {
        // skip past the rows in between down a lane on the left, instead of through their blocks
        const between = Object.keys(pos).map(Number).filter((j) => pos[j].y > a.y && pos[j].y < b.y);
        const lane = Math.min(...between.map((j) => pos[j].x), a.x, b.x) - 26 - (skips++ % 4) * 12;
        d = `M${x1},${y1} C${x1},${y1 + 34} ${lane},${y1 + 20} ${lane},${y1 + 60} L${lane},${y2 - 60} C${lane},${y2 - 20} ${x2},${y2 - 34} ${x2},${y2 - 2}`;
      } else {
        const dy = Math.max(40, (y2 - y1) * 0.5);
        d = `M${x1},${y1} C${x1},${y1 + dy} ${x2},${y2 - dy} ${x2},${y2 - 2}`;
      }
      el('path', { d, class: 'flow-line', 'marker-end': 'url(#arrowhead)' }, g);
      const k = outs[f.from].slice().sort((p, q) => pos[SM.flows[p].to].x - pos[SM.flows[q].to].x).indexOf(fi);
      const lg = el('g', { class: 'flow' }, gL);
      txt(lg, x1 + 5, y1 + 15 + k * 13, f.data.join(' \u00b7 '), { class: 'flow-label' });
      track(f, g); track(f, lg);
    });
    // feedback loops run up the right-hand side
    SM.flows.forEach((f, fi) => {
      if (!f.feedback) return;
      const a = pos[f.from], b = pos[f.to];
      const lane = fullW + 40 + (fi % 4) * 18;
      const g = el('g', { class: 'flow fb' }, gA);
      el('path', { d: `M${a.x + a.w},${a.y + a.h / 2} C${lane},${a.y + a.h / 2} ${lane},${b.y + b.h / 2} ${b.x + b.w + 2},${b.y + b.h / 2}`, class: 'flow-line', 'marker-end': 'url(#arrowhead)' }, g);
      const lg = el('g', { class: 'flow fb' }, gL);
      const apex = a.x + a.w + (lane - a.x - a.w) * 0.75;   // where the curve bulges furthest
      txt(lg, apex + 6, (a.y + a.h / 2 + b.y + b.h / 2) / 2 + 4, f.data.join(' \u00b7 '), { class: 'flow-label' });
      track(f, g); track(f, lg);
    });
    S.forEach((st, i) => {
      const p = pos[i];
      const g = el('g', { class: 'mblock' + (i === active ? ' on' : ''), 'data-stage': i, tabindex: 0, role: 'button', 'aria-label': st.title }, gB);
      const c = st.colour;
      el('rect', { x: p.x, y: p.y, width: p.w, height: p.h, rx: 9, class: 'mb-bg' }, g);
      el('rect', { x: p.x, y: p.y, width: 7, height: p.h, rx: 3.5, style: `fill:${c ? rgb(c) : '#9aa0a6'}` }, g);
      txt(g, p.x + 18, p.y + 22, String(i + 1).padStart(2, '0') + (st.count ? ` \u00b7 ${st.count} items` : ''), { class: 'mb-no' });
      txt(g, p.x + 18, p.y + 42, fit1(st.title, 24), { class: 'mb-title' });
      const t = el('title', {}, g); t.textContent = stageSummary(st);
      g.addEventListener('mouseenter', () => (arrows[i] || []).forEach((a) => a.classList.add('hl')));
      g.addEventListener('mouseleave', () => (arrows[i] || []).forEach((a) => a.classList.remove('hl')));
      g.addEventListener('keydown', (e) => { if (e.key === 'Enter') { const k = steps.findIndex((x) => x.id === st.step); if (k >= 0) goStep(k); } });
    });
    const maxY = Math.max(...Object.values(pos).map((p) => p.y + p.h));
    const hasFb = SM.flows.some((f) => f.feedback);
    state.mapBounds = [-20, -20, fullW + (hasFb ? 260 : 40), maxY + 60];
    frame(state.mapBounds, { pad: 20, maxK: 1.25, instant: true });
    renderCrumbs();
  }

  // ------------------------------------------------------------------ view / camera
  function applyView() {
    world.setAttribute('transform', `translate(${state.tx},${state.ty}) scale(${state.k})`);
    applyLOD();
    placePins();
  }
  function applyLOD() { svg.classList.toggle('lod-low', state.k < 0.42); }
  let anim = null;
  function frame(b, opts) {
    opts = opts || {};
    const W = wrap.clientWidth, H = wrap.clientHeight;
    if (!b || !W || !H) return;
    const pad = opts.pad == null ? 46 : opts.pad;
    let k = Math.min((W - pad * 2) / Math.max(b[2], 1), (H - pad * 2) / Math.max(b[3], 1));
    k = Math.min(opts.maxK || 2.2, Math.max(0.02, k));
    const tx = W / 2 - (b[0] + b[2] / 2) * k, ty = H / 2 - (b[1] + b[3] / 2) * k;
    const reduce = window.matchMedia && matchMedia('(prefers-reduced-motion: reduce)').matches;
    if (opts.instant || reduce) { Object.assign(state, { k, tx, ty }); applyView(); return; }
    const from = { k: state.k, tx: state.tx, ty: state.ty }, t0 = performance.now(), dur = 420;
    cancelAnimationFrame(anim);
    const stepFn = (now) => {
      const t = Math.min(1, (now - t0) / dur), e = 1 - Math.pow(1 - t, 3);
      // interpolate in log-zoom space so big zoom changes feel even
      const kk = Math.exp(Math.log(from.k) + (Math.log(k) - Math.log(from.k)) * e);
      const cxF = (W / 2 - from.tx) / from.k, cyF = (H / 2 - from.ty) / from.k;
      const cxT = (W / 2 - tx) / k, cyT = (H / 2 - ty) / k;
      const cx = cxF + (cxT - cxF) * e, cy = cyF + (cyT - cyF) * e;
      Object.assign(state, { k: kk, tx: W / 2 - cx * kk, ty: H / 2 - cy * kk });
      applyView();
      if (t < 1) anim = requestAnimationFrame(stepFn);
    };
    anim = requestAnimationFrame(stepFn);
  }
  function zoomAt(f, sx, sy) {
    const k = Math.min(6, Math.max(0.02, state.k * f));
    const r = k / state.k;
    state.tx = sx - (sx - state.tx) * r; state.ty = sy - (sy - state.ty) * r; state.k = k;
    applyView();
  }

  // pointer: drag to pan, wheel/pinch to zoom, click to inspect
  const ptrs = new Map();
  let drag = null, pinch = null;
  wrap.addEventListener('pointerdown', (e) => {
    if (e.target.closest('.zoom') || e.target.closest('.pin')) return;
    wrap.setPointerCapture(e.pointerId);
    ptrs.set(e.pointerId, [e.clientX, e.clientY]);
    if (ptrs.size === 1) drag = { x: e.clientX, y: e.clientY, tx: state.tx, ty: state.ty, moved: false, target: e.target };
    if (ptrs.size === 2) {
      const [a, b] = [...ptrs.values()];
      pinch = { d: Math.hypot(a[0] - b[0], a[1] - b[1]), k: state.k };
      drag = null;
    }
  });
  wrap.addEventListener('pointermove', (e) => {
    if (ptrs.has(e.pointerId)) ptrs.set(e.pointerId, [e.clientX, e.clientY]);
    if (pinch && ptrs.size === 2) {
      const [a, b] = [...ptrs.values()], r = wrap.getBoundingClientRect();
      const d = Math.hypot(a[0] - b[0], a[1] - b[1]);
      zoomAt((pinch.k * d / pinch.d) / state.k, (a[0] + b[0]) / 2 - r.left, (a[1] + b[1]) / 2 - r.top);
      return;
    }
    if (drag) {
      const dx = e.clientX - drag.x, dy = e.clientY - drag.y;
      if (Math.abs(dx) + Math.abs(dy) > 4) { drag.moved = true; wrap.classList.add('dragging'); hideTip(); }
      if (drag.moved) { state.tx = drag.tx + dx; state.ty = drag.ty + dy; applyView(); }
      return;
    }
    hover(e);
  });
  const endPtr = (e) => {
    ptrs.delete(e.pointerId);
    if (ptrs.size < 2) pinch = null;
    if (drag && !drag.moved && e.type === 'pointerup') {
      const node = drag.target.closest && drag.target.closest('.ob');
      if (node && state.view !== 'map') inspect(node.dataset.id);
      const mb = drag.target.closest && drag.target.closest('.mblock');
      if (mb) { const st = WT.stage_map.stages[+mb.dataset.stage]; const k = steps.findIndex((x) => x.id === st.step); if (k >= 0) goStep(k); }
    }
    if (!ptrs.size) { drag = null; wrap.classList.remove('dragging'); }
  };
  wrap.addEventListener('pointerup', endPtr);
  wrap.addEventListener('pointercancel', endPtr);
  wrap.addEventListener('pointerleave', hideTip);
  wrap.addEventListener('wheel', (e) => {
    e.preventDefault();
    const r = wrap.getBoundingClientRect();
    const dy = e.deltaMode === 1 ? e.deltaY * 16 : e.deltaY;
    zoomAt(Math.exp(-dy * (e.ctrlKey ? 0.01 : 0.0018)), e.clientX - r.left, e.clientY - r.top);
  }, { passive: false });
  $('#z-in').onclick = () => zoomAt(1.35, wrap.clientWidth / 2, wrap.clientHeight / 2);
  $('#z-out').onclick = () => zoomAt(1 / 1.35, wrap.clientWidth / 2, wrap.clientHeight / 2);
  $('#z-all').onclick = () => frame(state.view === 'map' ? state.mapBounds : M.docs[state.doc].bounds);
  $('#z-fit').onclick = () => {
    if (state.view === 'map') return frame(state.mapBounds);
    const s = steps[state.step];
    frame(state.mode === 'walk' && s && s.doc === state.doc ? s.focus : M.docs[state.doc].bounds);
  };
  new ResizeObserver(() => placePins()).observe(wrap);

  // hover tooltip + wire highlight
  let hot = null;
  function hover(e) {
    const node = e.target.closest && e.target.closest('.ob');
    const id = node ? node.dataset.id : null;
    if (id !== hot) {
      if (hot) highlight(hot, false);
      hot = id;
      if (id) highlight(id, true);
    }
    if (!id) return hideTip();
    const o = idx.obj[id], r = wrap.getBoundingClientRect();
    tip.innerHTML = `<b>${esc(objName(o))}</b> <span>${esc(o.type)}${libName(o) !== 'Grasshopper' ? ' · ' + esc(libName(o)) : ''}</span>`;
    tip.hidden = false;
    const x = e.clientX - r.left + 14, y = e.clientY - r.top + 14;
    tip.style.left = Math.min(x, r.width - tip.offsetWidth - 8) + 'px';
    tip.style.top = Math.min(y, r.height - tip.offsetHeight - 8) + 'px';
  }
  function hideTip() { tip.hidden = true; if (hot) { highlight(hot, false); hot = null; } }
  function highlight(id, on) {
    const n = idx.node[id];
    if (n) n.classList.toggle('hl', on);
    (idx.wiresOf[id] || []).forEach((w) => w.classList.toggle('hl', on));
    const g = idx.grp[id];
    if (g) g.classList.toggle('hl', on);
  }

  // ------------------------------------------------------------------ pins & focus
  let curPins = [];
  function setPins(pins, focusIds, focusBounds, dim) {
    curPins = pins || [];
    const gF = idx.gfocus;
    gF.innerHTML = '';
    curPins.forEach((p) => {
      const b = p.bounds, m = p.kind === 'group' ? 9 : 4;
      el('rect', { class: 'focus-ring', x: b[0] - m, y: b[1] - m, width: b[2] + 2 * m, height: b[3] + 2 * m, rx: 6 }, gF);
    });
    // dim everything outside the focus area
    const fb = focusBounds;
    const inside = (b) => fb && b && b[0] + b[2] > fb[0] - 30 && b[0] < fb[0] + fb[2] + 30 && b[1] + b[3] > fb[1] - 30 && b[1] < fb[1] + fb[3] + 30;
    Object.entries(idx.node).forEach(([id, n]) => n.classList.toggle('dim', !!(dim && fb && !inside(idx.obj[id].bounds))));
    Object.entries(idx.grp).forEach(([id, n]) => n.classList.toggle('dim', !!(dim && fb && !inside(idx.groupsById[id].bounds))));
    svg.querySelectorAll('.wire').forEach((w) => {
      const a = idx.obj[w.dataset.from], z = idx.obj[w.dataset.to];
      w.classList.toggle('dim', !!(dim && fb && !(inside(a && a.bounds) || inside(z && z.bounds))));
    });
    svg.querySelectorAll('.bifocal').forEach((b) => b.classList.toggle('dim', false));
    pinsEl.innerHTML = '';
    curPins.forEach((p) => {
      const d = document.createElement('button');
      d.type = 'button';
      d.className = 'pin'; d.textContent = p.n; d.dataset.n = p.n;
      d.title = p.label;
      d.onmouseenter = () => hotPin(p.n, true);
      d.onmouseleave = () => hotPin(p.n, false);
      d.onclick = () => {
        const li = notes.querySelector(`li[data-pin="${p.n}"]`);
        if (li) { li.scrollIntoView({ block: 'nearest', behavior: 'smooth' }); li.classList.add('hot'); setTimeout(() => li.classList.remove('hot'), 1200); }
      };
      pinsEl.appendChild(d);
    });
    placePins();
  }
  function placePins() {
    const nodes = pinsEl.children;
    const used = [];
    curPins.forEach((p, i) => {
      const n = nodes[i];
      if (!n) return;
      let x = p.bounds[0] * state.k + state.tx - 4, y = p.bounds[1] * state.k + state.ty - 4;
      // nudge pins that would sit on top of one another
      for (let tries = 0; tries < 6 && used.some((u) => Math.hypot(u[0] - x, u[1] - y) < 22); tries++) x += 24;
      used.push([x, y]);
      n.style.left = x + 'px'; n.style.top = y + 'px';
    });
  }
  function hotPin(n, on) {
    const p = curPins.find((q) => q.n == n);
    const node = pinsEl.querySelector(`[data-n="${n}"]`);
    if (node) node.classList.toggle('hot', on);
    const li = notes.querySelector(`li[data-pin="${n}"]`);
    if (li) li.classList.toggle('hot', on);
    if (p) highlight(p.id, on);
  }

  // ------------------------------------------------------------------ navigation
  function goStep(i, opts) {
    opts = opts || {};
    i = Math.max(0, Math.min(steps.length - 1, i));
    state.step = i; state.mode = 'walk'; state.inspecting = false; state.sel = null;
    const s = steps[i];
    if (s.view === 'map' && WT.stage_map) {
      renderMap(null);
    } else {
      state.view = 'canvas';
      if (state.doc !== s.doc || !idx.obj) render(s.doc);
      setPins(s.pins, s.focus_ids, s.focus, s.dim);
      frame(s.focus, { instant: opts.instant });
    }
    renderRail(); renderCrumbs(); renderStep(s);
    $('#step-select').value = String(i);
    if (!opts.noHash) { try { history.replaceState(null, '', '#' + s.id); } catch (e) { /* sandboxed */ } }
    notes.scrollTop = 0;
  }
  function goDoc(did, focusId) {
    if (!M.docs[did]) return;
    state.mode = 'explore'; state.inspecting = false;
    if (state.doc !== did || state.view === 'map') render(did);
    setPins([], null, null, false);
    renderRail(); renderCrumbs();
    if (focusId && (idx.obj[focusId] || idx.groupsById[focusId])) {
      const b = (idx.obj[focusId] || idx.groupsById[focusId]).bounds;
      frame([b[0] - 150, b[1] - 120, b[2] + 300, b[3] + 240]);
      if (idx.obj[focusId]) inspect(focusId); else renderDocSummary(did);
    } else {
      frame(M.docs[did].bounds);
      renderDocSummary(did);
    }
  }
  function select(id) {
    if (state.sel && idx.node[state.sel]) idx.node[state.sel].classList.remove('sel');
    state.sel = id;
    if (id && idx.node[id]) idx.node[id].classList.add('sel');
  }

  // ------------------------------------------------------------------ side panels
  function renderRail() {
    const rail = $('#rail');
    $('#mode-walk').classList.toggle('on', state.mode === 'walk');
    $('#mode-explore').classList.toggle('on', state.mode === 'explore');
    if (state.mode === 'walk') {
      let h = '';
      WT.parts.forEach((p) => {
        if (p.title) h += `<h2>${esc(p.title)}</h2>`;
        h += '<ol>' + p.steps.map((s) => `<li><a href="#${esc(s.id)}" data-step="${s.index}" class="${s.index === state.step ? 'on' : ''}"><span class="no">${String(s.index + 1).padStart(2, '0')}</span><span>${esc(s.title)}</span></a></li>`).join('') + '</ol>';
      });
      rail.innerHTML = h;
    } else {
      const entries = Object.entries(WT.paths).filter(([p, d]) => WT.doc_path[d] === p).sort((a, b) => a[0].localeCompare(b[0]));
      let h = '<h2>Canvases</h2><ol class="tree">';
      entries.forEach(([p, d]) => {
        const depth = p ? p.split('/').length : 0;
        const n = M.docs[d].objects.filter((o) => o.kind !== 'cluster_input' && o.kind !== 'cluster_output').length;
        h += `<li><a href="#" data-doc="${d}" class="${d === state.doc ? 'on' : ''}" style="padding-left:${14 + depth * 14}px"><span>${depth ? '<span class="lead">└ </span>' : ''}${esc(depth ? p.split('/').pop() : 'Main canvas')}</span><span class="cnt">${n}</span></a></li>`;
      });
      rail.innerHTML = h + '</ol>';
    }
  }
  function renderCrumbs() {
    const mapBtn = WT.stage_map ? `<a href="#" class="map-link" data-map="1">${state.view === 'map' ? '' : 'Stage map'}</a>` : '';
    if (state.view === 'map') {
      $('#crumbs').innerHTML = `<span class="kind">Map</span><span class="here">How the stages connect</span><span class="sep">&middot;</span><span class="hint2">click a stage to open it</span>`;
      return;
    }
    const p = WT.doc_path[state.doc];
    const parts = p ? p.split('/') : [];
    let h = `<span class="kind">${parts.length ? 'Cluster' : 'Canvas'}</span><a href="#" data-crumb="">Main canvas</a>`;
    parts.forEach((name, i) => {
      const sub = parts.slice(0, i + 1).join('/');
      h += `<span class="sep">›</span>` + (i === parts.length - 1 ? `<span class="here">${esc(name)}</span>` : `<a href="#" data-crumb="${esc(sub)}">${esc(name)}</a>`);
    });
    $('#crumbs').innerHTML = h + (mapBtn ? `<span class="spacer"></span>${mapBtn}` : '');
  }
  function stepNav(s) {
    const prev = steps[s.index - 1], next = steps[s.index + 1];
    return `<nav class="stepnav"><button type="button" data-step="${s.index - 1}" ${prev ? '' : 'disabled'}><small>Previous</small>${prev ? esc(prev.title) : ''}</button>` +
      `<button type="button" data-step="${s.index + 1}" ${next ? '' : 'disabled'}><small>Next</small>${next ? esc(next.title) : ''}</button></nav>`;
  }
  function stageFlows(s) {
    if (s.stage == null || !WT.stage_map) return '';
    const S = WT.stage_map.stages, F = WT.stage_map.flows;
    const link = (i) => { const k = steps.findIndex((x) => x.id === S[i].step); return `<a href="#" data-step="${k}">${esc(S[i].title)}</a>`; };
    const inn = F.filter((f) => f.to === s.stage).map((f) => `<li><span class="fdata">${esc(f.data.join(', '))}</span> from ${link(f.from)}</li>`);
    const out = F.filter((f) => f.from === s.stage).map((f) => `<li><span class="fdata">${esc(f.data.join(', '))}</span> to ${link(f.to)}</li>`);
    if (!inn.length && !out.length) return '';
    return `<div class="flows">${inn.length ? `<div><h4>Receives</h4><ul>${inn.join('')}</ul></div>` : ''}${out.length ? `<div><h4>Sends</h4><ul>${out.join('')}</ul></div>` : ''}</div>`;
  }
  function renderStep(s) {
    const part = WT.parts[s.part];
    const eyebrow = s.kind === 'stage' ? `Stage ${s.stage + 1} of ${WT.stage_map ? WT.stage_map.stages.length : '?'}` : s.kind === 'concept' ? 'Key concept' : esc(part.title || 'Step');
    notes.innerHTML = `<p class="eyebrow">${eyebrow} &middot; ${s.index + 1} of ${steps.length}</p><h2>${esc(s.title)}</h2>${s.html}${stageFlows(s)}${stepNav(s)}` +
      (s.index === steps.length - 1 ? footer() : '');
    wireNotes();
  }
  function footer() {
    return `<p class="meta-foot">Built from <code>${esc(WT.meta.source)}</code> on ${esc(WT.meta.built)}. Canvas drawings are generated from the .gh file itself.</p>`;
  }
  function wireNotes() {
    notes.querySelectorAll('ol.callouts li[data-pin]').forEach((li) => {
      const n = li.dataset.pin;
      li.onmouseenter = () => hotPin(n, true);
      li.onmouseleave = () => hotPin(n, false);
      li.onclick = (e) => {
        if (e.target.closest('a')) return;
        const p = curPins.find((q) => q.n == n);
        if (!p) return;
        const b = p.bounds;
        frame([b[0] - 60, b[1] - 60, b[2] + 120, b[3] + 120], { maxK: 1.8 });
      };
    });
  }

  // lists every step that talks about an object, so the inspector can link back
  function mentionsOf(id) {
    const out = [];
    steps.forEach((s) => {
      s.pins.forEach((p) => {
        if (p.id !== id) return;
        const tmp = document.createElement('div');
        tmp.innerHTML = s.html;
        const li = tmp.querySelector(`li[data-pin="${p.n}"] div`);
        out.push({ s, html: li ? li.innerHTML : '' });
      });
    });
    return out;
  }

  function connList(o, p, side) {
    const d = M.docs[state.doc];
    const names = [];
    d.wires.forEach((w) => {
      if (side === 'in' && w.to === o.id && (w.to_param || null) === (p ? p.id : null)) names.push(w.from);
      if (side === 'out' && w.from === o.id && (w.from_param || null) === (p ? p.id : null)) names.push(w.to);
    });
    return names.map((id) => `<a href="#" data-obj="${id}">${esc(objName(idx.obj[id]))}</a>`).join(', ');
  }
  function fmtVal(v) {
    if (Array.isArray(v)) return v.map(fmtVal).join(', ');
    if (typeof v === 'number') return String(Math.round(v * 10000) / 10000);
    return String(v);
  }
  function paramList(o, list, side) {
    if (!list || !list.length) return '<p class="pconn">none</p>';
    return '<ul class="plist">' + list.map((p) => {
      const nick = (p.nick || '').trim(), name = (p.name || '').trim();
      const conn = connList(o, p, side);
      let src = '';
      if (side === 'in') src = conn ? `from ${conn}` : (p.value != null ? `set to <code>${esc(fmtVal(p.value))}</code>` : 'not connected');
      else src = conn ? `to ${conn}` : 'not connected';
      const flags = (p.flags || []).map((f) => `<span class="chip">${f}</span>`).join('');
      return `<li><span class="pname">${esc(name)}</span> ${nick && nick !== name ? `<span class="pnick">(${esc(nick)})</span>` : ''} ${flags}` +
        `${p.desc ? `<span class="pdesc">${esc(p.desc)}</span>` : ''}<span class="pconn">${src}</span></li>`;
    }).join('') + '</ul>';
  }

  function inspect(id) {
    const o = idx.obj[id];
    if (!o) return;
    select(id);
    state.inspecting = true;
    const note = WT.component_notes[(o.type || '').toLowerCase().trim()] || WT.component_notes[(o.name || '').toLowerCase().trim()];
    const lib = libName(o);
    let h = `<button type="button" class="back" id="back">← ${state.mode === 'walk' ? 'Back to step ' + (state.step + 1) : 'Back to ' + esc(docTitle(state.doc))}</button>`;
    h += `<p class="eyebrow">${esc(o.kind === 'cluster' ? 'Cluster' : o.kind === 'script' ? 'Script component' : o.type)}</p><h2>${esc(objName(o))}</h2>`;
    h += `<p><span class="chip plugin">${esc(lib)}</span><span class="chip">${esc(o.type)}</span>${o.preview_off ? '<span class="chip">preview off</span>' : ''}${o.disabled ? '<span class="chip">disabled</span>' : ''}</p>`;
    if (o.desc) h += `<p>${esc(o.desc)}</p>`;
    if (note) h += `<h3>What it does here</h3>${note}`;
    const ment = mentionsOf(id);
    if (ment.length) {
      h += '<h3>In the walkthrough</h3>' + ment.map((m) => `<p>${m.html} <a href="#" data-step="${m.s.index}">Step ${m.s.index + 1}: ${esc(m.s.title)}</a></p>`).join('');
    }
    if (o.kind === 'cluster') {
      h += `<button type="button" class="btn" data-doc="${o.doc}">Open cluster ›</button>`;
    }
    if (o.kind === 'slider') h += `<dl class="kv"><dt>Value</dt><dd><code>${fmtVal(o.val)}</code></dd><dt>Range</dt><dd>${fmtVal(o.min)} to ${fmtVal(o.max)}</dd><dt>Decimals</dt><dd>${o.digits}</dd></dl>`;
    if (o.kind === 'toggle') h += `<dl class="kv"><dt>Currently</dt><dd><code>${o.val ? 'True' : 'False'}</code></dd></dl>`;
    if (o.kind === 'valuelist') h += '<h3>Options</h3><ul>' + o.options.map((q) => `<li>${q.selected ? '<strong>' : ''}${esc(q.name)}${q.selected ? '</strong> (selected)' : ''} <code>${esc(q.expr)}</code></li>`).join('') + '</ul>';
    if (o.kind === 'panel') {
      h += (o.sources && o.sources.length)
        ? `<p>This panel displays live data from ${connList(o, null, 'in')}.</p>`
        : `<h3>Panel text</h3><pre><code>${esc(o.text || '')}</code></pre>`;
      const out = connList(o, null, 'out');
      if (out) h += `<p>Feeds ${out}.</p>`;
    }
    if (o.kind === 'scribble') h += `<pre><code>${esc(o.text)}</code></pre>`;
    if (o.kind === 'swatch') h += `<p><span class="swatch-big" style="background:${o.colour ? rgba(o.colour) : '#888'}"></span> <code>rgba(${o.colour ? [o.colour.r, o.colour.g, o.colour.b, o.colour.a].join(', ') : ''})</code></p>`;
    if (['param', 'relay', 'cluster_input', 'cluster_output', 'swatch', 'slider', 'toggle', 'valuelist', 'button'].includes(o.kind)) {
      const inn = connList(o, null, 'in'), out = connList(o, null, 'out');
      if (o.value != null) h += `<dl class="kv"><dt>Stored value</dt><dd><code>${esc(fmtVal(o.value))}</code></dd></dl>`;
      if (inn) h += `<p>Receives data from ${inn}.</p>`;
      if (out) h += `<p>Sends data to ${out}.</p>`;
      if (o.kind === 'cluster_input') h += `<p>This is an <strong>input</strong> of the cluster: it brings data in from the canvas outside.</p>`;
      if (o.kind === 'cluster_output') h += `<p>This is an <strong>output</strong> of the cluster: it passes data back out to the canvas.</p>`;
    }
    if (o.inputs) h += `<h3>Inputs</h3>${paramList(o, o.inputs, 'in')}<h3>Outputs</h3>${paramList(o, o.outputs, 'out')}`;
    if (o.kind === 'script') h += `<h3>Source (${esc(o.language)})</h3><pre><code>${esc(o.code)}</code></pre>`;
    notes.innerHTML = h;
    notes.scrollTop = 0;
    $('#back').onclick = () => {
      select(null);
      if (state.mode === 'walk') { state.inspecting = false; renderStep(steps[state.step]); }
      else renderDocSummary(state.doc);
    };
  }

  function renderDocSummary(did) {
    const d = M.docs[did];
    const isMain = did === 'main';
    const ins = d.objects.filter((o) => o.kind === 'cluster_input').sort((a, b) => a.bounds[1] - b.bounds[1]);
    const outs = d.objects.filter((o) => o.kind === 'cluster_output').sort((a, b) => a.bounds[1] - b.bounds[1]);
    const inner = d.objects.filter((o) => o.kind === 'cluster');
    const scripts = d.objects.filter((o) => o.kind === 'script');
    const about = steps.filter((s) => s.doc === did);
    const named = d.groups.filter((g) => !g.label_only && g.bounds && g.nick && g.nick.trim() && g.member_objects.length > 1);
    let h = `<p class="eyebrow">${isMain ? 'Canvas' : 'Cluster'}</p><h2>${esc(docTitle(did))}</h2>`;
    if (!isMain && d.used_in) {
      const users = d.used_in.map((u) => `<a href="#" data-doc="${u.doc}" data-focus="${u.object}">${esc(docTitle(u.doc))}</a>`);
      h += `<p>Used ${d.used_in.length > 1 ? d.used_in.length + ' times, ' : ''}in ${[...new Set(users)].join(', ')}.</p>`;
    }
    if (about.length) h += '<h3>Explained in</h3><ul>' + about.map((s) => `<li><a href="#" data-step="${s.index}">Step ${s.index + 1}: ${esc(s.title)}</a></li>`).join('') + '</ul>';
    else if (!isMain) h += `<aside><p>No written notes for this cluster yet. Click any component to see what it is and how it is wired.</p></aside>`;
    const hook = (o) => {
      const nm = (o.nick || '').trim() || o.name;
      return `<li><a href="#" data-obj="${o.id}" class="pname">${esc(nm)}</a>${o.desc ? `<span class="pdesc">${esc(o.desc)}</span>` : ''}</li>`;
    };
    if (ins.length) h += `<h3>Inputs</h3><ul class="plist">${ins.map(hook).join('')}</ul>`;
    if (outs.length) h += `<h3>Outputs</h3><ul class="plist">${outs.map(hook).join('')}</ul>`;
    if (named.length) h += '<h3>Groups on this canvas</h3><ul>' + named.map((g) => `<li><a href="#" data-group="${g.id}">${esc(g.nick.trim())}</a></li>`).join('') + '</ul>';
    if (inner.length) h += '<h3>Clusters inside</h3><ul>' + inner.map((o) => `<li><a href="#" data-doc="${o.doc}">${esc(objName(o))}</a></li>`).join('') + '</ul>';
    if (scripts.length) h += '<h3>Scripts</h3><ul>' + scripts.map((o) => `<li><a href="#" data-obj="${o.id}">${esc(objName(o))}</a> (${esc(o.language)})</li>`).join('') + '</ul>';
    const counts = {};
    d.objects.forEach((o) => { counts[o.kind] = (counts[o.kind] || 0) + 1; });
    h += `<p class="meta-foot">${d.objects.length} objects, ${d.wires.length} wires.</p>`;
    notes.innerHTML = h;
    notes.scrollTop = 0;
  }

  // one delegated click handler for links in notes / rail / crumbs
  document.addEventListener('click', (e) => {
    const a = e.target.closest('[data-step],[data-doc],[data-obj],[data-crumb],[data-group],[data-map],a.ref');
    if (!a || a.closest('#wrap')) return;
    e.preventDefault();
    if (a.dataset.map) {
      const cur = steps[state.step];
      state.mode = 'walk';
      renderMap(cur && cur.stage != null ? cur.stage : null);
      renderRail();
      return;
    }
    if (a.dataset.goto) { const k = steps.findIndex((x) => x.id === a.dataset.goto); if (k >= 0) goStep(k); return; }
    if (a.classList.contains('ref')) {
      const did = a.dataset.doc, id = a.dataset.id;
      if (!id) return goDoc(did);
      if (did === state.doc) {
        const o = idx.obj[id] || idx.groupsById[id];
        const b = o.bounds;
        frame([b[0] - 80, b[1] - 80, b[2] + 160, b[3] + 160], { maxK: 1.8 });
        highlight(id, true); setTimeout(() => highlight(id, false), 1600);
        if (idx.obj[id]) inspect(id);
      } else goDoc(did, id);
      return;
    }
    if (a.dataset.step != null) return goStep(+a.dataset.step);
    if (a.dataset.crumb != null) return goDoc(WT.paths[a.dataset.crumb]);
    if (a.dataset.doc) return goDoc(a.dataset.doc, a.dataset.focus);
    if (a.dataset.group) {
      const g = idx.groupsById[a.dataset.group];
      if (g) frame(g.bounds);
      return;
    }
    if (a.dataset.obj) {
      const o = idx.obj[a.dataset.obj];
      if (o) { frame([o.bounds[0] - 120, o.bounds[1] - 100, o.bounds[2] + 240, o.bounds[3] + 200], { maxK: 1.8 }); inspect(o.id); }
    }
  });
  $('#mode-walk').onclick = () => goStep(state.step);
  $('#mode-explore').onclick = () => goDoc(state.doc || 'main');
  const sel = $('#step-select');
  sel.innerHTML = steps.map((s) => `<option value="${s.index}">${s.index + 1}. ${esc(s.title)}</option>`).join('');
  sel.onchange = () => goStep(+sel.value);
  document.addEventListener('keydown', (e) => {
    if (e.target.closest('input,select,textarea') || e.metaKey || e.ctrlKey || e.altKey) return;
    if (e.key === 'ArrowRight' && state.mode === 'walk') goStep(state.step + 1);
    if (e.key === 'ArrowLeft' && state.mode === 'walk') goStep(state.step - 1);
    if (e.key === 'Escape' && state.inspecting) $('#back') && $('#back').click();
  });

  // ------------------------------------------------------------------ boot
  $('#doc-sub').textContent = WT.meta.subtitle || '';
  let start = 0;
  const hash = (location.hash || '').slice(1);
  if (hash) { const f = steps.findIndex((s) => s.id === hash); if (f >= 0) start = f; }
  if (steps.length) {
    requestAnimationFrame(() => goStep(start, { instant: true, noHash: true }));
  } else {
    render('main'); requestAnimationFrame(() => goDoc('main'));
  }
})();
