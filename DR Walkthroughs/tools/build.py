"""
build.py - build the interactive walkthrough from a .gh file + markdown notes.

    python3 tools/build.py [path/to/script.gh]

  1. extracts the .gh into a JSON model            (gh_extract.py)
  2. reads content/walkthrough.md + content/components.md
  3. resolves every [reference] in the notes to real objects in the file
  4. writes ONE self-contained HTML file (open it in any browser, no server)
  5. prints a report: broken references + groups/clusters with no notes yet

If no .gh path is given, the newest .gh in the walkthrough folder is used.
See README.md for the notes format.
"""
import glob, html, json, os, re, sys, datetime
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
from gh_extract import extract

CONTENT = os.path.join(ROOT, 'content')
VIEWER = os.path.join(HERE, 'viewer')
OUT = os.path.join(ROOT, 'DR_Walkthrough.html')

warnings = []


def warn(msg):
    warnings.append(msg)


def norm(s):
    return re.sub(r'\s+', ' ', (s or '')).strip().lower()


# --------------------------------------------------------------------------
# model helpers
# --------------------------------------------------------------------------
class Model:
    def __init__(self, m):
        self.m = m
        self.docs = m['docs']
        self.paths = {}      # 'DR robotic Motions/DFL weaver' -> doc id
        self.doc_path = {}   # doc id -> path (first found)
        self._walk('main', '')

    def _walk(self, did, path):
        if path in self.paths:
            return
        self.paths[path] = did
        self.doc_path.setdefault(did, path)
        for ob in sorted(self.docs[did]['objects'], key=lambda o: (o['bounds'] or [0, 0])[1::-1]):
            if ob['kind'] == 'cluster':
                p = (path + '/' if path else '') + (ob['nick'] or ob['name']).strip()
                n = 2
                while p in self.paths and self.paths[p] != ob['doc']:
                    p = re.sub(r' \(\d+\)$', '', p) + f' ({n})'   # two different clusters, same name
                    n += 1
                if p not in self.paths:
                    self._walk(ob['doc'], p)

    def find_doc(self, ref):
        ref = (ref or '').strip().strip('/')
        if ref.lower() in ('', 'main', 'canvas'):
            return 'main'
        if ref in self.docs:
            return ref
        for p, d in self.paths.items():
            if norm(p) == norm(ref):
                return d
        # unique leaf-name match
        leaf = [d for p, d in self.paths.items() if norm(p.split('/')[-1]) == norm(ref)]
        if leaf:
            if len(set(leaf)) > 1:
                warn(f'doc "{ref}" is ambiguous; using the first. Give the full path, e.g. '
                     + ' or '.join(f'"{p}"' for p, d in self.paths.items() if d in leaf[:2]))
            return leaf[0]
        warn(f'doc "{ref}" not found. Known clusters: ' + ', '.join(sorted(p for p in self.paths if p)))
        return None

    def resolve(self, did, ref, context='', prefer_group=False):
        """ref -> (kind, id, bounds, label) inside a document."""
        d = self.docs[did]
        ref = ref.strip()
        scope = None
        if ' @ ' in ref:
            ref, scope = [x.strip() for x in ref.split(' @ ', 1)]
        objs = d['objects']
        groups = [g for g in d['groups'] if not g.get('label_only') and g.get('bounds')]
        if scope:
            sg = [g for g in groups if norm(g['nick']) == norm(scope)]
            if not sg:
                warn(f'{context}: scope group "{scope}" not found in {self.label(did)}')
            else:
                gb = sg[0]['bounds']
                inside = lambda b: b and b[0] >= gb[0] - 1 and b[1] >= gb[1] - 1 and \
                    b[0] + b[2] <= gb[0] + gb[2] + 1 and b[1] + b[3] <= gb[1] + gb[3] + 1
                objs = [o for o in objs if inside(o.get('bounds'))]
                groups = [g for g in groups if inside(g['bounds']) and g is not sg[0]]
        if re.fullmatch(r'#[0-9a-fA-F]{6,}', ref):
            pre = ref[1:].lower()
            hits = [('object', o) for o in objs if o['id'].startswith(pre)] + \
                   [('group', g) for g in groups if g['id'].startswith(pre)]
        else:
            r = norm(ref)
            ghits = [('group', g) for g in groups if norm(g['nick']) == r]
            hits = ghits if (prefer_group and ghits) else \
                [('object', o) for o in objs if norm(o.get('nick')) == r and o.get('bounds')]
            if not hits:
                hits = ghits
            if not hits:
                hits = [('object', o) for o in objs if o.get('bounds') and
                        (norm(o.get('name')) == r or norm(o.get('type')) == r)]
            if not hits:  # panel / scribble text start
                hits = [('object', o) for o in objs if o.get('bounds') and o['kind'] in ('scribble', 'panel')
                        and norm(o.get('text')).startswith(r)]
        if not hits:
            warn(f'{context}: "{ref}" not found in {self.label(did)}')
            return None
        if len(hits) > 1:
            hits.sort(key=lambda h: (h[1]['bounds'][0], h[1]['bounds'][1]))
            warn(f'{context}: "{ref}" matches {len(hits)} things in {self.label(did)}; using the left-most. '
                 f'Disambiguate with "{ref} @ <group name>" or "#{hits[0][1]["id"][:8]}"')
        kind, ob = hits[0]
        return {'kind': kind, 'id': ob['id'], 'bounds': ob['bounds'],
                'label': (ob.get('nick') or ob.get('name') or '').strip()}

    def label(self, did):
        p = self.doc_path.get(did)
        return 'main canvas' if p == '' else f'cluster "{p}"'


# --------------------------------------------------------------------------
# tiny markdown renderer (enough for notes: paragraphs, lists, tables,
# code blocks, > tips, **bold**, *italic*, `code`, [links](url), [[refs]])
# --------------------------------------------------------------------------
def inline(s, refs):
    s = html.escape(s, quote=False)
    s = re.sub(r'`([^`]+)`', lambda m: '<code>' + m.group(1) + '</code>', s)
    s = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', s)
    s = re.sub(r'(?<![\w*])\*(?!\s)(.+?)(?<!\s)\*(?!\w)', r'<em>\1</em>', s)

    def ref(m):
        text = m.group(1)
        label = text.split(' @ ')[0].lstrip('#')
        if '|' in text:
            text, label = [x.strip() for x in text.split('|', 1)]
        r = refs(html.unescape(text))
        if not r:
            return f'<span class="ref broken">{label}</span>'
        if r.get('step'):
            return f'<a href="#{r["step"]}" class="ref" data-goto="{r["step"]}">{label}</a>'
        return (f'<a href="#" class="ref" data-doc="{r["doc"]}" data-id="{r["id"]}">{label}</a>')
    s = re.sub(r'\[\[(.+?)\]\]', ref, s)
    s = re.sub(r'\[([^\]]+)\]\((https?://[^)]+)\)', r'<a href="\2" target="_blank" rel="noopener">\1</a>', s)
    return s


def render_md(text, refs, pin):
    out, lines, i = [], text.split('\n'), 0
    while i < len(lines):
        ln = lines[i]
        if not ln.strip():
            i += 1
            continue
        if ln.startswith('??'):
            buf = [ln[2:].strip()]
            i += 1
            while i < len(lines) and lines[i].strip() and not lines[i].startswith(('??', '#', '-', '|', '>', '```')):
                buf.append(lines[i].strip())
                i += 1
            out.append('<aside class="q"><b>To confirm</b> ' + inline(' '.join(buf), refs) + '</aside>')
            continue
        if ln.startswith('```'):
            j = i + 1
            while j < len(lines) and not lines[j].startswith('```'):
                j += 1
            out.append('<pre><code>' + html.escape('\n'.join(lines[i + 1:j])) + '</code></pre>')
            i = j + 1
            continue
        m = re.match(r'(#{3,4})\s+(.*)', ln)
        if m:
            lvl = len(m.group(1))
            out.append(f'<h{lvl}>{inline(m.group(2), refs)}</h{lvl}>')
            i += 1
            continue
        if ln.startswith('>'):
            buf = []
            while i < len(lines) and lines[i].startswith('>'):
                buf.append(lines[i][1:].strip())
                i += 1
            first = buf[0]
            cls = 'tip'
            mm = re.match(r'\*\*(Warning|Important|Tip|Note)[:.]?\*\*', first, re.I)
            if mm and mm.group(1).lower() in ('warning', 'important'):
                cls = 'warn'
            out.append(f'<aside class="{cls}">' + ''.join(
                f'<p>{inline(b, refs)}</p>' for b in ' '.join(buf).split('  ') if b) + '</aside>')
            continue
        if ln.startswith('|'):
            rows = []
            while i < len(lines) and lines[i].startswith('|'):
                cells = [c.strip() for c in lines[i].strip().strip('|').split('|')]
                if not all(re.fullmatch(r':?-+:?', c) for c in cells):
                    rows.append(cells)
                i += 1
            t = '<div class="tbl"><table><thead><tr>' + ''.join(
                f'<th>{inline(c, refs)}</th>' for c in rows[0]) + '</tr></thead><tbody>'
            for r in rows[1:]:
                t += '<tr>' + ''.join(f'<td>{inline(c, refs)}</td>' for c in r) + '</tr>'
            out.append(t + '</tbody></table></div>')
            continue
        if re.match(r'\s*([-*]|\d+\.)\s', ln):
            ordered = bool(re.match(r'\s*\d+\.', ln))
            items = []
            while i < len(lines) and (re.match(r'\s*([-*]|\d+\.)\s', lines[i]) or
                                      (lines[i].startswith('  ') and lines[i].strip() and items)):
                if re.match(r'\s*([-*]|\d+\.)\s', lines[i]):
                    items.append(re.sub(r'\s*([-*]|\d+\.)\s+', '', lines[i], count=1))
                else:
                    items[-1] += ' ' + lines[i].strip()
                i += 1
            pinned = [re.match(r'\[([^\]]+)\](?!\()\s*(.*)', it) for it in items]
            if all(pinned):
                # callout list: every item starts with [ref] -> numbered pins
                h = '<ol class="callouts">'
                for pm in pinned:
                    n, r = pin(pm.group(1))
                    lab = pm.group(1).split(' @ ')[0].lstrip('#')
                    if '|' in pm.group(1):
                        lab = pm.group(1).split('|', 1)[1].strip()
                    attrs = f' data-pin="{n}"' + (f' data-id="{r["id"]}"' if r else ' data-broken="1"')
                    h += (f'<li{attrs}><span class="pin-no">{n}</span><div><b class="co-name">'
                          f'{html.escape(lab)}</b> {inline(pm.group(2), refs)}</div></li>')
                out.append(h + '</ol>')
            else:
                tag = 'ol' if ordered else 'ul'
                out.append(f'<{tag}>' + ''.join(f'<li>{inline(it, refs)}</li>' for it in items) + f'</{tag}>')
            continue
        buf = []
        while i < len(lines) and lines[i].strip() and not re.match(r'(```|#{3,4}\s|>|\||\?\?|\s*([-*]|\d+\.)\s)', lines[i]):
            buf.append(lines[i].strip())
            i += 1
        out.append('<p>' + inline(' '.join(buf), refs) + '</p>')
    return '\n'.join(out)


# --------------------------------------------------------------------------
# walkthrough.md -> steps
# --------------------------------------------------------------------------
def slug(s):
    return re.sub(r'[^a-z0-9]+', '-', s.lower()).strip('-')


def read_parts(path):
    """Split a notes file into meta + parts/steps (raw)."""
    text = open(path, encoding='utf-8').read()
    text = re.sub(r'<!--.*?-->', '', text, flags=re.S)
    meta, parts = {}, []
    part = step = None
    body = []

    def flush():
        if step is not None:
            step['_body'] = '\n'.join(body)
            part['steps'].append(step)

    for ln in text.split('\n'):
        if ln.startswith('# '):
            flush(); step = None; body = []
            part = {'title': ln[2:].strip(), 'steps': []}
            parts.append(part)
        elif ln.startswith('## '):
            flush(); body = []
            if part is None:
                part = {'title': '', 'steps': []}
                parts.append(part)
            step = {'title': ln[3:].strip(), '_dir': {}}
        elif step is not None and re.match(r'@(\w+):', ln) and not ''.join(body).strip():
            k, v = ln[1:].split(':', 1)
            step['_dir'][k.strip()] = v.strip()
        elif step is None and part is None and re.match(r'(\w+):', ln):
            k, v = ln.split(':', 1)
            meta[k.strip()] = v.strip()
        elif step is not None:
            body.append(ln)
    flush()
    return meta, parts


def union_bounds(bs):
    bs = [b for b in bs if b]
    if not bs:
        return None
    x0 = min(b[0] for b in bs); y0 = min(b[1] for b in bs)
    x1 = max(b[0] + b[2] for b in bs); y1 = max(b[1] + b[3] for b in bs)
    return [x0, y0, x1 - x0, y1 - y0]


def split_refs(s):
    return [x.strip() for x in re.split(r',\s+', s) if x.strip()]   # ', ' separates; '40,000' does not


def process_steps(parts, model, questions):
    seen_ids = set()
    stages = []
    for p in parts:
        for s in p['steps']:
            d = s.pop('_dir')
            kind = 'step'
            m = re.match(r'(Stage|Concept):\s*(.*)', s['title'])
            if m:
                kind, s['title'] = m.group(1).lower(), m.group(2).strip()
            s['kind'] = kind
            sid = d.get('id') or slug(s['title'])
            while sid in seen_ids:
                sid += '-2'
            seen_ids.add(sid)
            s['id'] = sid
            ctx = f'step "{s["title"]}"'
            did = model.find_doc(d.get('doc', 'main')) or 'main'
            s['doc'] = did
            s['view'] = d.get('view', 'canvas')
            pins = []

            def refs(r, did=did, ctx=ctx):
                if r.startswith('doc:'):   # [[doc:Cluster path|label]] -> open a cluster
                    t = model.find_doc(r[4:])
                    return {'doc': t, 'id': ''} if t else None
                if r.startswith('step:'):  # [[step:step-id|label]] -> jump to a step
                    return {'doc': '', 'id': '', 'step': r[5:].strip()}
                if '::' in r:              # [[Cluster path::object]]
                    dp, r2 = r.split('::', 1)
                    t = model.find_doc(dp)
                    if not t:
                        return None
                    x = model.resolve(t, r2, ctx)
                    return dict(x, doc=t) if x else None
                x = model.resolve(did, r, ctx)
                return dict(x, doc=did) if x else None

            def pin(r, did=did, ctx=ctx):
                x = model.resolve(did, r.split('|')[0], ctx, prefer_group=True)
                pins.append(dict(x, n=len(pins) + 1) if x else {'n': len(pins) + 1, 'broken': r})
                return len(pins), x

            body = s.pop('_body').strip()
            questions.extend(f'{s["title"]}: {q.strip()}' for q in re.findall(r'^\?\?\s*(.+)$', body, re.M))
            s['html'] = render_md(body, refs, pin)
            s['pins'] = [p_ for p_ in pins if 'id' in p_]
            fb = []
            if kind == 'stage':
                covers = split_refs(d.get('covers', s['title']))
                rects, ids = [], []
                for c in covers:
                    x = model.resolve(did, c, ctx + ' @covers', prefer_group=True)
                    if x:
                        rects.append(x['bounds'])
                        ids.append(x['id'])
                s['stage'] = len(stages)
                plain = re.sub(r'<[^>]+>', '', s['html'])
                first = re.split(r'(?<=[.!?])\s', plain.strip(), maxsplit=1)[0] if plain.strip() else ''
                stages.append({'title': s['title'], 'rects': rects, 'ids': ids, 'step': s['id'],
                               'summary': d.get('summary') or first, 'column': d.get('column')})
                fb = list(rects)
                s.setdefault('focus_ids', []).extend(ids)
            focus = d.get('focus', '')
            if focus.lower() == 'all':
                fb = [model.docs[did].get('bounds')]
            elif focus:
                fb = []
                for f in split_refs(focus):
                    x = model.resolve(did, f, ctx + ' @focus', prefer_group=True)
                    if x:
                        fb.append(x['bounds'])
                        s.setdefault('focus_ids', []).append(x['id'])
            if not fb:
                fb = [p_['bounds'] for p_ in s['pins']] or [model.docs[did].get('bounds')]
            s['focus'] = union_bounds(fb)
            s['dim'] = d.get('dim', 'yes').lower() not in ('no', 'false', 'off')
    return stages


def stage_map(model, stages, renames):
    """Flows between the brief's stages, computed from the real wires."""
    if not stages:
        return None
    from stages import flows
    doc = model.docs['main']
    fl, owner = flows(doc, stages)
    # columns follow the data, but the order stages are written in decides which
    # way a loop runs: a flow back to an earlier stage is drawn as feedback
    rank = {}
    for i in range(len(stages)):
        rank[i] = max([rank[a] + 1 for a, b, _ in fl if b == i and a < i] or [0])
    out = []
    for a, b, names in fl:
        names = list(dict.fromkeys(renames.get(n, n) for n in names))
        out.append({'from': a, 'to': b, 'data': names, 'feedback': a > b})
    colours = {}
    for i, s in enumerate(stages):
        for gid in s['ids']:
            g = next((g for g in doc['groups'] if g['id'] == gid), None)
            if g and g.get('colour') and g['colour']['a'] > 0:
                colours[i] = g['colour']
                break
    counts = defaultdict(int)
    for v in owner.values():
        counts[v] += 1
    unassigned = [o for o in doc['objects'] if o['id'] not in owner and o.get('bounds')
                  and o['kind'] not in ('scribble',)]
    for u in unassigned:
        warn(f'main canvas: "{(u.get("nick") or u["type"]).strip()}" is not inside any stage (@covers)')
    for i, s in enumerate(stages):
        s['rank'] = int(s['column']) if s.get('column') else rank.get(i, 0)
        s['colour'] = colours.get(i)
        s['count'] = counts[i]
        s['y'] = min(r[1] for r in s['rects']) if s['rects'] else 0
        s['x'] = min(r[0] for r in s['rects']) if s['rects'] else 0
    return {'stages': stages, 'flows': out}


def parse_components(path):
    """content/components.md: '## Type Name' sections -> notes shown in the inspector."""
    notes = {}
    if not os.path.exists(path):
        return notes
    cur, buf = None, []
    for ln in open(path, encoding='utf-8').read().split('\n') + ['## ']:
        if ln.startswith('## '):
            if cur:
                notes[norm(cur)] = render_md('\n'.join(buf).strip(), lambda r: None, lambda r: (0, None))
            cur, buf = ln[3:].strip(), []
        elif cur:
            buf.append(ln)
    return notes


# --------------------------------------------------------------------------
def coverage(model, parts):
    """Named groups and clusters that no step mentions yet (copies of a cluster count once)."""
    mentioned, docs_with_steps = set(), set()
    for p in parts:
        for s in p['steps']:
            docs_with_steps.add(s['doc'])
            mentioned.update(s.get('focus_ids', []))
            mentioned.update(x['id'] for x in s['pins'])
            mentioned.update(re.findall(r'data-id="([0-9a-f-]{36})"', s['html']))
            docs_with_steps.update(re.findall(r'data-doc="([^"]+)" data-id=""', s['html']))
    titled = {norm(model.docs[d]['title']) for d in docs_with_steps}
    todo, seen = [], set()
    for path, did in sorted(model.paths.items(), key=lambda kv: kv[0]):
        d = model.docs[did]
        key = norm(d['title']) + '|' + str(len(d['objects']))
        if model.doc_path.get(did) != path or key in seen:
            continue
        seen.add(key)
        documented = did in docs_with_steps or norm(d['title']) in titled
        missing = sorted({g['nick'].strip() for g in d['groups']
                          if not g.get('label_only') and g.get('bounds') and g['nick'].strip()
                          and g['id'] not in mentioned and len(g['member_objects']) > 1})
        if did in docs_with_steps and missing:
            todo.append((path or '(main canvas)', True, missing))
        elif not documented:
            todo.append((path or '(main canvas)', False, []))
    return todo


def main():
    gh = sys.argv[1] if len(sys.argv) > 1 else None
    if not gh:
        cands = sorted(glob.glob(os.path.join(ROOT, '*.gh')), key=os.path.getmtime)
        if not cands:
            sys.exit('No .gh file given and none found in ' + ROOT)
        gh = cands[-1]
    print(f'Reading {os.path.basename(gh)} ...')
    raw = extract(gh)
    model = Model(raw)
    meta, parts = {}, []
    for fn in ('brief.md', 'walkthrough.md'):
        path = os.path.join(CONTENT, fn)
        if os.path.exists(path):
            m_, p_ = read_parts(path)
            meta.update({k: v for k, v in m_.items() if k not in meta})
            parts += p_
    questions = []
    stages = process_steps(parts, model, questions)
    renames = dict(tuple(x.strip() for x in r.split('=', 1)) for r in split_refs(meta.get('rename', '')) if '=' in r)
    smap = stage_map(model, stages, renames)
    comp_notes = parse_components(os.path.join(CONTENT, 'components.md'))

    data = {
        'meta': dict(meta, source=os.path.basename(gh),
                     built=datetime.datetime.now().strftime('%d %b %Y %H:%M')),
        'model': raw, 'paths': model.paths, 'doc_path': model.doc_path,
        'parts': parts, 'component_notes': comp_notes, 'stage_map': smap,
    }
    js = json.dumps(data, separators=(',', ':')).replace('</', '<\\/')
    tpl = open(os.path.join(VIEWER, 'template.html'), encoding='utf-8').read()
    css = open(os.path.join(VIEWER, 'viewer.css'), encoding='utf-8').read()
    vjs = open(os.path.join(VIEWER, 'viewer.js'), encoding='utf-8').read()
    page = (tpl.replace('/*__CSS__*/', css)
               .replace('/*__DATA__*/', 'window.WT=' + js + ';')
               .replace('/*__JS__*/', vjs)
               .replace('__TITLE__', html.escape(meta.get('title') or meta.get('name') or 'Grasshopper walkthrough')))
    with open(OUT, 'w', encoding='utf-8') as f:
        f.write(page)
    nsteps = sum(len(p['steps']) for p in parts)
    print(f'Wrote {os.path.relpath(OUT, os.getcwd())}  ({len(page) // 1024} KB, {nsteps} steps, '
          f'{len(raw["docs"])} canvases)')

    if warnings:
        print(f'\n{len(warnings)} reference problem(s) - fix these in content/*.md:')
        for w in dict.fromkeys(warnings):
            print('  !', w)
    if questions:
        print(f'\n{len(questions)} open question(s) marked ?? in the notes:')
        for q in questions:
            print('  ?', q)
    todo = coverage(model, parts)
    if todo:
        print('\nNot yet explained (candidates for new notes):')
        for path, has_step, missing in todo:
            if not has_step:
                print(f'  - cluster "{path}": no step yet (students can still explore it)')
            if missing:
                print(f'  - {path}: groups not mentioned: ' + ', '.join(f'"{g}"' for g in missing))


if __name__ == '__main__':
    main()
