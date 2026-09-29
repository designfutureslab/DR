"""
stages.py - find the major areas of a Grasshopper canvas and the data flowing between them.

A "stage" is a region of the main canvas: normally a named group, or an unnamed
group that carries a scribble title. Every object on the canvas is assigned to
the stage whose group contains it (or the nearest stage). Wires that cross from
one stage to another become "flows", labelled with the name of the data.

    python3 tools/stages.py script.gh          # prints the detected map
    python3 tools/stages.py script.gh --draft  # writes content/brief.draft.md

Used by build.py to draw the stage map from the brief.
"""
import math, os, re, sys
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def _contains(outer, inner, tol=2):
    return (inner[0] >= outer[0] - tol and inner[1] >= outer[1] - tol and
            inner[0] + inner[2] <= outer[0] + outer[2] + tol and inner[1] + inner[3] <= outer[1] + outer[3] + tol)


def _gap(a, b):
    dx = max(0, max(a[0], b[0]) - min(a[0] + a[2], b[0] + b[2]))
    dy = max(0, max(a[1], b[1]) - min(a[1] + a[3], b[1] + b[3]))
    return math.hypot(dx, dy)


def detect(doc):
    """Auto-detect candidate stages on a document (usually the main canvas)."""
    objs = {o['id']: o for o in doc['objects'] if o.get('bounds')}
    cands = []
    for g in doc['groups']:
        if g.get('label_only') or not g.get('bounds') or len(g['member_objects']) + len(g['member_groups']) < 2:
            continue
        title = (g.get('nick') or '').strip()
        if not title:
            scribs = [objs[m] for m in g['member_objects'] if m in objs and objs[m]['kind'] == 'scribble']
            if scribs:
                title = scribs[0]['text'].strip().split('\n')[0]
        if not title:
            continue
        cands.append({'title': title, 'group': g['id'], 'bounds': g['bounds'],
                      'size': len(g['member_objects'])})
    # keep outermost areas only (a named group inside another named area is a detail)
    cands.sort(key=lambda c: -c['bounds'][2] * c['bounds'][3])
    top = []
    for c in cands:
        if not any(_contains(t['bounds'], c['bounds']) for t in top):
            top.append(c)
    return top


def assign(doc, stages):
    """object id -> stage index, using stage 'bounds' lists (any of several rects)."""
    owner = {}
    for o in doc['objects']:
        b = o.get('bounds')
        if not b:
            continue
        best, bestd = None, 1e18
        for i, s in enumerate(stages):
            for sb in s['rects']:
                if _contains(sb, b, tol=10):
                    area = sb[2] * sb[3]
                    if area < bestd:        # smallest containing area wins
                        best, bestd = i, area
        if best is None:
            d = [(min(_gap(b, sb) for sb in s['rects']), i) for i, s in enumerate(stages) if s['rects']]
            if d and min(d)[0] < 250:
                best = min(d)[1]
        if best is not None:
            owner[o['id']] = best
    return owner


def flows(doc, stages):
    """[(from_stage, to_stage, [data names])] for wires crossing stage boundaries."""
    owner = assign(doc, stages)
    objs = {o['id']: o for o in doc['objects']}
    pname = {}
    for o in doc['objects']:
        for p in o.get('outputs', []):
            pname[p['id']] = (p.get('nick') or p.get('name') or '').strip()
    upstream = defaultdict(list)
    for w in doc['wires']:
        upstream[w['to']].append(w)
    passthrough = {'relay', 'param'}

    def label(w, depth=0):
        """Name of the data on a wire; looks through relays, dams and plain params."""
        src = objs[w['from']]
        name = pname.get(w['from_param']) if w['from_param'] else None
        generic = not name or len(name) <= 2
        if depth < 6 and (src['kind'] in passthrough or src['type'] == 'Data Dam') and upstream[src['id']] \
                and (generic or len((src.get('nick') or '').strip()) <= 3):
            return label(upstream[src['id']][0], depth + 1)
        if generic:
            name = (src.get('nick') or src.get('name') or '').strip()
        return name

    out = defaultdict(list)
    for w in doc['wires']:
        a, b = owner.get(w['from']), owner.get(w['to'])
        if a is None or b is None or a == b:
            continue
        lab = label(w)
        if lab and lab not in out[(a, b)]:
            out[(a, b)].append(lab)
    return [(a, b, names) for (a, b), names in out.items()], owner


def order(stages, fl):
    """Left-to-right order: by data dependency, then canvas x."""
    pred = defaultdict(set)
    for a, b, _ in fl:
        pred[b].add(a)
    rank = {}

    def rk(i, seen=()):
        if i in rank:
            return rank[i]
        if i in seen:
            return 0
        r = max([rk(p, seen + (i,)) + 1 for p in pred[i]] or [0])
        rank[i] = r
        return r
    for i in range(len(stages)):
        rk(i)
    return rank


def draft(model, path):
    doc = model['docs']['main']
    st = detect(doc)
    for s in st:
        s['rects'] = [s['bounds']]
    fl, owner = flows(doc, st)
    rank = order(st, fl)
    idx = sorted(range(len(st)), key=lambda i: (rank[i], st[i]['bounds'][0]))
    objs = {o['id']: o for o in doc['objects']}
    lines = ['name: ' + doc['title'], 'purpose: ?? one or two sentences: what does this script make, and for whom?',
             'audience: ?? who will read this (e.g. first-year students new to Grasshopper)', '', '# The big picture', '',
             '## Overview', '@view: map', '', '?? Describe, in plain language, how the stages below work together.', '']
    for i in idx:
        s = st[i]
        ins = [f'{st[a]["title"]} ({", ".join(n)})' for a, b, n in fl if b == i]
        outs = [f'{st[b]["title"]} ({", ".join(n)})' for a, b, n in fl if a == i]
        mem = [objs[k] for k, v in owner.items() if v == i]
        clusters = sorted({(o.get('nick') or '').strip() for o in mem if o['kind'] == 'cluster'})
        controls = sorted({(o.get('nick') or '').strip() for o in mem
                           if o['kind'] in ('slider', 'toggle', 'valuelist', 'button') and (o.get('nick') or '').strip()})
        g = next(g for g in doc['groups'] if g['id'] == s['group'])
        cover = s['title'] if (g.get('nick') or '').strip() == s['title'] else '#' + s['group'][:8]
        lines += [f'## Stage: {s["title"]}', f'@covers: {cover}', '',
                  '?? What is this stage for, and what should a user do here?', '']
        lines += [f'- [{c} @ {s["title"]}] ?? what does this control?' if cover == s['title'] else f'- [{c}] ?? what does this control?'
                  for c in controls[:8]]
        lines += ['', f'<!-- detected: receives {"; ".join(ins) or "nothing"} | sends {"; ".join(outs) or "nothing"}'
                  + (f' | clusters: {", ".join(clusters)}' if clusters else '') + ' -->', '']
    lines += ['## Concept: ?? name a key idea a newcomer must understand', '', '?? explanation', '',
              '## Workflow', '', '1. ?? the real-world steps around the script (lab set-up, calibration, running)', '',
              '## Gotchas', '', '- ?? common mistakes and safety notes', '']
    with open(path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines))
    return path


if __name__ == '__main__':
    from gh_extract import extract
    m = extract(sys.argv[1])
    if '--draft' in sys.argv:
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        print('wrote', draft(m, os.path.join(root, 'content', 'brief.draft.md')))
    else:
        doc = m['docs']['main']
        st = detect(doc)
        for s in st:
            s['rects'] = [s['bounds']]
        fl, owner = flows(doc, st)
        rank = order(st, fl)
        for i in sorted(range(len(st)), key=lambda i: (rank[i], st[i]['bounds'][0])):
            print(f'[{rank[i]}] {st[i]["title"]}  ({sum(1 for v in owner.values() if v == i)} objects)')
        print()
        for a, b, n in sorted(fl, key=lambda f: (rank[f[0]], rank[f[1]])):
            print(f'  {st[a]["title"]}  ->  {st[b]["title"]}:  {", ".join(n)}')
