"""
gh_tidy.py - safe, non-behavioural clean-up of a Grasshopper .gh file.

    python3 tools/gh_tidy.py input.gh [output.gh]

Never overwrites the input. Default output: <input>_tidy.gh

What it changes (none of this alters what the definition computes):
  * removes empty "orphan" groups (groups whose members no longer exist,
    typically left behind when components were collapsed into a cluster)
  * fixes spelling in display text: nicknames, group names, scribbles,
    value-list labels, cluster descriptions and note panels that are not
    wired to anything. Text that flows into the solution (wired panels,
    Python variable names, value-list expressions) is never touched.
  * names unnamed cluster inputs/outputs ("Relay", "Data"...) inside clusters
    with the name they already carry on the outside of the cluster
  * re-lays out cluster interiors left-to-right following the wires,
    keeping tidy groups intact; a new layout is only kept when it has fewer
    wire crossings/overlaps than the original. The main canvas layout is kept.

Afterwards it re-reads both files and checks that every object, wire, value,
setting and script is identical apart from positions and display text.
"""
import os, re, sys, math, zlib, json
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import gh_raw as R

GROUP = 'c552a431-af5b-46a9-a8a4-0fcbc27ef596'
SCRIBBLE = '7f5c6c55-f846-4a08-9c9a-cfdc285cc6fe'
PANEL = '59e0b89a-e487-49f8-bab8-b5bab16be14c'
CLUSTER = 'f31d8d7a-7536-4ac8-9c96-fde6ecda4d0a'
CLUSTER_IN = '448de216-3a12-43cf-a135-e3bfafc87744'
CLUSTER_OUT = 'a4b285fe-2e13-4204-b65c-189aa6704da5'
PY3 = '719467e6-7cf5-4848-99b0-c5dd57e5442c'

TYPOS = {
    'instrucitons': 'instructions', 'fixutres': 'fixtures', 'tollerance': 'tolerance',
    'tollarance': 'tolerance', 'pressue': 'pressure', 'inital': 'initial', 'whipe': 'wipe',
    'refil': 'refill', 'porgram': 'program', 'graphted': 'grafted', 'comands': 'commands',
    'exeed': 'exceed', 'choise': 'choice', 'callibrated': 'calibrated', 'orientd': 'oriented',
    'visulaization': 'visualization', 'analisis': 'analysis', 'basesd': 'based',
    'retratction': 'retraction', 'sharpenning': 'sharpening', 'danm': 'dam',
    'programable': 'programmable', 'strait': 'straight', 'blunten': 'blunt',
}
PHRASES = {'Pent Pressure': 'Pen Pressure'}
GENERIC_HOOK_NAMES = {'', 'relay', 'data', 'num', 'number', 'a', 'b', 'd', 'g', 't', 'l', 'i', 'pt',
                      'point', 'plane', 'pln', 'list', 'index', 'gate', 'geometry', 'result', 'r',
                      'stream', 's(0)', 's(1)', 'item', 'mesh', 'curve', 'text', 'tree', 'boolean',
                      'bool', 'domain', 'colour', 'target', 'program', 'moved', 'm', 'c', 'pl'}

log = defaultdict(list)


def fix_text(s):
    if not s:
        return s
    out = s
    for a, b in PHRASES.items():
        out = out.replace(a, b)

    def rep(m):
        w = m.group(0)
        fixed = TYPOS.get(w.lower())
        if not fixed:
            return w
        if w.isupper():
            return fixed.upper()
        if w[0].isupper():
            return fixed[0].upper() + fixed[1:]
        return fixed
    return re.sub(r'[A-Za-z]+', rep, out)


# ---------------------------------------------------------------- doc access
def objects_chunk(doc):
    d = doc.chunks[0] if doc.name == 'Root' else doc
    return d.child('DefinitionObjects')


def container(o):
    return o.child('Container')


def iid(o):
    c = container(o)
    return c.get('InstanceGuid') if c else None


def sources(chunk):
    return [it.value for it in chunk.items if it.name == 'Source']


def param_chunks(cont):
    pd = cont.child('ParameterData')
    ins = (pd.children('InputParam') if pd else []) + cont.children('param_input')
    outs = (pd.children('OutputParam') if pd else []) + cont.children('param_output')
    return ins, outs


def obj_info(doc):
    """id -> dict(chunk, bounds, kind, group info...) + wires between object ids."""
    oc = objects_chunk(doc)
    objs, groups, owner = {}, {}, {}
    for o in oc.children('Object'):
        c = container(o)
        if c is None:
            continue
        guid, i = o.get('GUID'), c.get('InstanceGuid')
        if guid == GROUP:
            col = c.get('Colour')
            groups[i] = {'chunk': o, 'members': [it.value for it in c.items if it.name == 'ID'],
                         'alpha': col[0] if col else 255, 'nick': c.get('NickName', ''),
                         'border': c.get('Border')}
            continue
        a = c.child('Attributes')
        b = a.get('Bounds') if a else None
        if guid == SCRIBBLE and not b:
            ca, cc = c.get('Ca'), c.get('Cc')
            b = (ca[0], ca[1], cc[0] - ca[0], cc[1] - ca[1]) if ca and cc else None
        ins, outs = param_chunks(c)
        objs[i] = {'chunk': o, 'guid': guid, 'bounds': b, 'ins': ins, 'outs': outs, 'cont': c}
        owner[i] = i
        for p in ins + outs:
            owner[p.get('InstanceGuid')] = i
    wires = []
    for i, ob in objs.items():
        for holder in [ob['cont']] + ob['ins']:
            for s in sources(holder):
                if s in owner and owner[s] != i:
                    wires.append((owner[s], i))
    return objs, groups, wires


# ---------------------------------------------------------------- safe edits
def remove_orphan_groups(doc, where):
    objs, groups, _ = obj_info(doc)
    alive = set(objs)
    dead = set()
    changed = True
    while changed:
        changed = False
        for gid, g in groups.items():
            if gid in dead:
                continue
            if not any(m in alive or (m in groups and m not in dead) for m in g['members']):
                dead.add(gid)
                changed = True
    if not dead:
        return 0
    oc = objects_chunk(doc)
    oc.chunks = [o for o in oc.chunks if not (o.name == 'Object' and iid(o) in dead)]
    for i, o in enumerate(oc.chunks):
        o.index = i
    oc.item('ObjectCount').value = len(oc.chunks)
    # drop references to removed groups from surviving groups
    for gid, g in groups.items():
        if gid in dead:
            continue
        c = container(g['chunk'])
        ids = [it for it in c.items if it.name == 'ID']
        keep = [it for it in ids if it.value not in dead]
        if len(keep) != len(ids):
            pos = c.items.index(ids[0])
            others = [it for it in c.items if it.name != 'ID']
            for n, it in enumerate(keep):
                it.index = n
            c.items = others[:pos] + keep + others[pos:]
            c.item('ID_Count').value = len(keep)
    named = sorted({groups[g]['nick'] for g in dead if groups[g]['nick'].strip()})
    log['orphan groups'].append(f'{where}: removed {len(dead)} empty group(s)'
                                + (f' (named: {", ".join(named)})' if named else ''))
    return len(dead)


def fix_spelling(doc, where):
    objs, groups, _ = obj_info(doc)
    wired = set()
    for ob in objs.values():
        for holder in [ob['cont']] + ob['ins']:
            wired.update(sources(holder))
    n = 0

    def apply(item, what):
        nonlocal n
        if item is None or item.type != R.T_STRING:
            return
        old = item.value
        new = fix_text(old)
        if new != old:
            item.value = new
            n += 1
            log['spelling'].append(f'{where}: {what} "{old.strip()[:60]}" -> "{new.strip()[:60]}"')

    for gid, g in groups.items():
        apply(container(g['chunk']).item('NickName'), 'group')
    for i, ob in objs.items():
        c = ob['cont']
        is_script = ob['guid'] == PY3 or c.child('Script') is not None
        apply(c.item('NickName'), 'name')
        for key in ('CustomNickName', 'CustomName'):
            apply(c.item(key), 'name')
        if ob['guid'] in (CLUSTER_IN, CLUSTER_OUT):
            apply(c.item('Name'), 'cluster hook')
        if ob['guid'] == SCRIBBLE:
            apply(c.item('Text'), 'scribble')
        if ob['guid'] == PANEL and not sources(c) and i not in wired:
            apply(c.item('UserText'), 'note panel')
        if c.item('ClusterDocument') is not None:
            apply(c.item('Description'), 'cluster description')
        for li in c.children('ListItem'):
            apply(li.item('Name'), 'list label')
        if not is_script:   # script parameter nicknames are Python variable names
            for p in ob['ins'] + ob['outs']:
                apply(p.item('NickName'), 'parameter')
                if c.item('ClusterDocument') is not None:
                    apply(p.item('Name'), 'parameter')
    return n


def name_hooks(inner, outer_obj, where):
    """Give unnamed hooks inside a cluster the name used outside."""
    c = container(outer_obj)
    pm = c.child('ParamMap')
    if not pm:
        return
    keys = [it.value for it in pm.items if it.name == 'Key']
    vals = [it.value for it in pm.items if it.name == 'Value']
    ins, outs = param_chunks(c)
    outer = {p.get('InstanceGuid'): p for p in ins + outs}
    objs, _, _ = obj_info(inner)
    for k, v in zip(keys, vals):
        p, h = outer.get(k), objs.get(v)
        if not p or not h:
            continue
        name = (p.get('NickName') or p.get('Name') or '').strip()
        hc = h['cont']
        cur = (hc.get('CustomNickName') or hc.get('NickName') or '').strip()
        if not name or name.lower() in GENERIC_HOOK_NAMES or cur.lower() not in GENERIC_HOOK_NAMES or cur == name:
            continue
        done = False
        for key in ('CustomNickName', 'NickName'):
            it = hc.item(key)
            if it is not None and it.type == R.T_STRING:
                it.value = name
                done = True
        if done:
            log['cluster hooks'].append(f'{where}: "{cur or "(blank)"}" -> "{name}"')


# ---------------------------------------------------------------- layout
def shift_object(o, dx, dy):
    for ch in o.walk():
        for it in ch.items:
            if it.type == R.T_RECTF and it.name == 'Bounds':
                x, y, w, h = it.value
                it.value = (x + dx, y + dy, w, h)
            elif it.type == R.T_POINTF and it.name in ('Pivot', 'Ca', 'Cb', 'Cc', 'Cd'):
                x, y = it.value
                it.value = (x + dx, y + dy)


def box(b, pad=(8, 20, 8, 8)):
    """object bounds -> layout box with room for group blobs and name tags (l, t, r, b pads)."""
    return (b[0] - pad[0], b[1] - pad[1], b[0] + b[2] + pad[2], b[1] + b[3] + pad[3])


def union(bs):
    return (min(b[0] for b in bs), min(b[1] for b in bs), max(b[2] for b in bs), max(b[3] for b in bs))


def quality(objs, wires, pos=None):
    """Lower is better: wire crossings + overlaps + a little wire length."""
    def B(i):
        b = objs[i]['bounds']
        if pos and i in pos:
            return (pos[i][0], pos[i][1], b[2], b[3])
        return b
    segs = []
    length = 0
    for a, z in wires:
        ba, bz = B(a), B(z)
        if not ba or not bz:
            continue
        p = (ba[0] + ba[2], ba[1] + ba[3] / 2)
        q = (bz[0], bz[1] + bz[3] / 2)
        segs.append((p, q, a, z))
        length += math.hypot(q[0] - p[0], q[1] - p[1]) + max(0, p[0] - q[0]) * 2  # backwards wires cost more
    def ccw(A, Bp, C):
        return (C[1] - A[1]) * (Bp[0] - A[0]) > (Bp[1] - A[1]) * (C[0] - A[0])
    cross = 0
    for i in range(len(segs)):
        p1, q1, a1, z1 = segs[i]
        for j in range(i + 1, len(segs)):
            p2, q2, a2, z2 = segs[j]
            if {a1, z1} & {a2, z2}:
                continue
            if ccw(p1, p2, q2) != ccw(q1, p2, q2) and ccw(p1, q1, p2) != ccw(p1, q1, q2):
                cross += 1
    ids = [i for i in objs if objs[i]['bounds']]
    overlap = 0
    bx = {i: box(B(i), (2, 14, 2, 2)) for i in ids}
    for n, i in enumerate(ids):
        for j in ids[n + 1:]:
            a, b = bx[i], bx[j]
            w = min(a[2], b[2]) - max(a[0], b[0])
            h = min(a[3], b[3]) - max(a[1], b[1])
            if w > 0 and h > 0:
                overlap += 1
    return {'crossings': cross, 'overlaps': overlap, 'length': int(length),
            'score': cross + overlap * 3 + length / 4000}


class Unit:
    def __init__(self, members, objs):
        self.members = list(members)
        self.box = union([box(objs[m]['bounds']) for m in self.members])
        self.x, self.y = self.box[0], self.box[1]
        self.w, self.h = self.box[2] - self.box[0], self.box[3] - self.box[1]
        self.rank = 0
        self.hook = None   # 'in' / 'out'


def layered(units, edges, gap_x=70, gap_y=16):
    """Sugiyama-style layered layout, left to right.
    units: list[Unit]; edges: dict or set of (u, v) unit indices (dict values = wire counts).
    Returns {unit index: (x, y)} for the top-left of each unit box."""
    n = len(units)
    weight = defaultdict(int)
    for e in edges:
        if e[0] != e[1]:
            weight[e] += edges[e] if isinstance(edges, dict) else 1
    succ, pred = defaultdict(set), defaultdict(set)
    for a, b in weight:
        succ[a].add(b)
        pred[b].add(a)
    # 1. break cycles (possible once objects are merged into blocks)
    state, removed = {}, set()
    sys.setrecursionlimit(10000)

    def dfs(u):
        state[u] = 1
        for v in sorted(succ[u], key=lambda i: units[i].x):
            if state.get(v) == 1:
                removed.add((u, v))
            elif not state.get(v):
                dfs(v)
        state[u] = 2
    for u in sorted(range(n), key=lambda i: units[i].x):
        if not state.get(u):
            dfs(u)
    for a, b in removed:
        succ[a].discard(b)
        pred[b].discard(a)
        succ[b].add(a)
        pred[a].add(b)
        weight[(b, a)] += weight.pop((a, b))

    # 2. ranks: longest path, then pull sources (sliders, panels...) next to their consumers
    rank = {}

    def rk(u):
        if u not in rank:
            rank[u] = 0
            rank[u] = max([rk(p) + 1 for p in pred[u]] or [0])
        return rank[u]
    for u in range(n):
        rk(u)
    for u in sorted(range(n), key=lambda i: -rank[i]):
        if not pred[u] and succ[u] and units[u].hook != 'in':
            rank[u] = max(0, min(rank[v] for v in succ[u]) - 1)
    if any(u.hook == 'in' for u in units):
        for u in range(n):
            rank[u] = 0 if units[u].hook == 'in' else rank[u] + 1
    outs = [u for u in range(n) if units[u].hook == 'out']
    if outs:
        top = max([rank[u] for u in range(n) if units[u].hook != 'out'] or [0]) + 1
        for u in outs:
            rank[u] = top

    # 3. dummy nodes so long wires take part in ordering
    H = {u: units[u].h for u in range(n)}
    Y0 = {u: units[u].y + units[u].h / 2 for u in range(n)}
    rank_of = dict(rank)
    ledges = defaultdict(int)          # (a, b) between adjacent ranks -> weight
    nid = n
    for (a, b), w in weight.items():
        ra, rb = rank_of[a], rank_of[b]
        prev = a
        for r in range(ra + 1, rb):
            d = nid
            nid += 1
            rank_of[d] = r
            H[d] = 6
            Y0[d] = Y0[a] + (Y0[b] - Y0[a]) * (r - ra) / max(1, rb - ra)
            ledges[(prev, d)] += w
            prev = d
        ledges[(prev, b)] += w
    lsucc, lpred = defaultdict(list), defaultdict(list)
    for (a, b), w in ledges.items():
        lsucc[a].append((b, w))
        lpred[b].append((a, w))
    ranks = sorted(set(rank_of.values()))
    cols = {r: sorted([v for v in rank_of if rank_of[v] == r], key=lambda v: Y0[v]) for r in ranks}

    # 4. crossing minimisation: weighted median sweeps + adjacent transpositions
    def pos_map():
        return {v: i for r in ranks for i, v in enumerate(cols[r])}

    def crossings_between(r, P):
        es = [(P[a], P[b], w) for a in cols[r] for b, w in lsucc[a]]
        c = 0
        for i in range(len(es)):
            for j in range(i + 1, len(es)):
                if (es[i][0] - es[j][0]) * (es[i][1] - es[j][1]) < 0:
                    c += es[i][2] * es[j][2]
        return c

    def total(P):
        return sum(crossings_between(r, P) for r in ranks[:-1])
    best = {r: list(cols[r]) for r in ranks}
    P = pos_map()
    best_c = total(P)
    for it in range(20):
        down = it % 2 == 0
        seq = ranks[1:] if down else ranks[-2::-1]
        for r in seq:
            nb = lpred if down else lsucc

            def med(v):
                ps = sorted(P[u] for u, w in nb[v] for _ in range(min(w, 3)))
                if not ps:
                    return P[v]
                m = len(ps) // 2
                return ps[m] if len(ps) % 2 else (ps[m - 1] + ps[m]) / 2
            cols[r].sort(key=lambda v: (med(v), P[v]))
            for i, v in enumerate(cols[r]):
                P[v] = i
        # transpose pass
        improved = True
        while improved:
            improved = False
            for r in ranks:
                col = cols[r]
                for i in range(len(col) - 1):
                    before = sum(crossings_between(q, P) for q in (r - 1, r) if q in cols and q + 1 in cols)
                    col[i], col[i + 1] = col[i + 1], col[i]
                    P[col[i]], P[col[i + 1]] = i, i + 1
                    after = sum(crossings_between(q, P) for q in (r - 1, r) if q in cols and q + 1 in cols)
                    if after < before:
                        improved = True
                    else:
                        col[i], col[i + 1] = col[i + 1], col[i]
                        P[col[i]], P[col[i + 1]] = i, i + 1
        c = total(P)
        if c < best_c:
            best_c, best = c, {q: list(cols[q]) for q in ranks}
    cols = best

    # 5. x: one column per rank
    colx, x = {}, 0
    for r in ranks:
        colx[r] = x
        real = [units[v].w for v in cols[r] if v < n]
        x += (max(real) if real else 20) + gap_x

    # 6. y: stack, then relax each node towards its neighbours (keeping order)
    y = {}
    for r in ranks:
        cy = 0
        for v in cols[r]:
            y[v] = cy
            cy += H[v] + (gap_y if v < n else 4)
    nbrs = defaultdict(list)
    for (a, b), w in ledges.items():
        nbrs[a].append((b, w))
        nbrs[b].append((a, w))
    for it in range(30):
        seq = ranks if it % 2 == 0 else ranks[::-1]
        for r in seq:
            col = cols[r]
            want = []
            for v in col:
                ns = nbrs[v]
                if ns:
                    tw = sum(w for _, w in ns)
                    want.append(sum((y[u] + H[u] / 2) * w for u, w in ns) / tw - H[v] / 2)
                else:
                    want.append(y[v])
            gaps = [(gap_y if col[i] < n else 4) for i in range(len(col))]
            fwd = list(want)
            for i in range(1, len(col)):
                fwd[i] = max(fwd[i], fwd[i - 1] + H[col[i - 1]] + gaps[i - 1])
            bwd = list(want)
            for i in range(len(col) - 2, -1, -1):
                bwd[i] = min(bwd[i], bwd[i + 1] - H[col[i]] - gaps[i])
            for i, v in enumerate(col):
                y[v] = (fwd[i] + bwd[i]) / 2
    return {u: (colx[rank_of[u]], y[u]) for u in range(n)}


def layout_doc(doc, where):
    objs, groups, wires = obj_info(doc)
    objs = {i: o for i, o in objs.items() if o['bounds']}
    wires = [(a, z) for a, z in wires if a in objs and z in objs]
    if len(objs) < 4 or not wires:
        return None
    before = quality(objs, wires)
    ox0 = min(o['bounds'][0] for o in objs.values())
    oy0 = min(o['bounds'][1] for o in objs.values())
    connected = {a for a, _ in wires} | {z for _, z in wires}

    # 1. rigid blocks from tidy leaf groups; loose groups get laid out on their own first
    parent = {i: i for i in objs}

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i
    new_pos = {}          # object id -> (x, y) top-left of bounds after layout
    leaf = []
    for gid, g in groups.items():
        if g['alpha'] == 0:
            continue
        mem = [m for m in g['members'] if m in objs]
        sub = [m for m in g['members'] if m in groups and groups[m]['alpha'] > 0]
        if len(mem) >= 2 and not sub:
            leaf.append(mem)
    for mem in leaf:
        for m in mem[1:]:
            parent[find(m)] = find(mem[0])
    blocks = defaultdict(list)
    for i in objs:
        blocks[find(i)].append(i)
    for root_, mem in blocks.items():
        if len(mem) < 3:
            continue
        area = sum(objs[m]['bounds'][2] * objs[m]['bounds'][3] for m in mem)
        bb = union([box(objs[m]['bounds'], (0, 0, 0, 0)) for m in mem])
        if area / max(1, (bb[2] - bb[0]) * (bb[3] - bb[1])) > 0.22:
            continue  # dense enough: keep the author's arrangement
        inner_w = [(a, z) for a, z in wires if a in mem and z in mem]
        if not inner_w:
            continue
        us = [Unit([m], objs) for m in mem]
        ui = {m: k for k, m in enumerate(mem)}
        p = layered(us, {(ui[a], ui[z]) for a, z in inner_w}, gap_x=40, gap_y=12)
        for k, m in enumerate(mem):
            b = objs[m]['bounds']
            new_pos[m] = (bb[0] + p[k][0] + (b[0] - us[k].box[0]), bb[1] + p[k][1] + (b[1] - us[k].box[1]))

    def cur(m):
        return new_pos.get(m, tuple(objs[m]['bounds'][:2]))

    # 2. unconnected notes join their nearest neighbour; scribble titles float on top
    titles = [i for i in objs if objs[i]['guid'] == SCRIBBLE]
    loose = [i for i in objs if i not in connected and i not in titles and len(blocks[find(i)]) == 1]
    anchors = [i for i in objs if i not in loose and i not in titles]
    for i in loose:
        b = objs[i]['bounds']
        best = min(anchors, key=lambda j: _gap(b, objs[j]['bounds']), default=None)
        if best is not None and _gap(b, objs[best]['bounds']) < 400:
            parent[find(i)] = find(best)
    blocks = defaultdict(list)
    for i in objs:
        if i not in titles:
            blocks[find(i)].append(i)

    # 3. global layered layout of blocks
    keys = list(blocks)
    units = []
    for k in keys:
        mem = blocks[k]
        u = Unit(mem, objs)
        # account for any internal re-layout
        bs = [box((cur(m)[0], cur(m)[1], objs[m]['bounds'][2], objs[m]['bounds'][3])) for m in mem]
        u.box = union(bs)
        u.x, u.y, u.w, u.h = u.box[0], u.box[1], u.box[2] - u.box[0], u.box[3] - u.box[1]
        if len(mem) == 1 and objs[mem[0]]['guid'] == CLUSTER_IN:
            u.hook = 'in'
        if len(mem) == 1 and objs[mem[0]]['guid'] == CLUSTER_OUT:
            u.hook = 'out'
        units.append(u)
    which = {m: n for n, k in enumerate(keys) for m in blocks[k]}
    edges = defaultdict(int)
    for a, z in wires:
        if a in which and z in which:
            edges[(which[a], which[z])] += 1
    pos = layered(units, edges)
    final = {}
    for n, k in enumerate(keys):
        u = units[n]
        for m in blocks[k]:
            cx, cy = cur(m)
            final[m] = (pos[n][0] + (cx - u.box[0]), pos[n][1] + (cy - u.box[1]))
    # titles above the top-left corner
    if final:
        fx0 = min(p[0] for p in final.values())
        fy0 = min(p[1] for p in final.values())
        for t_i, t in enumerate(sorted(titles, key=lambda i: objs[i]['bounds'][1])):
            h = objs[t]['bounds'][3]
            final[t] = (fx0, fy0 - 40 - h - t_i * (h + 8))
    # keep the drawing roughly where it was on the canvas
    fx0 = min(p[0] for p in final.values())
    fy0 = min(p[1] for p in final.values())
    final = {m: (round(p[0] - fx0 + ox0), round(p[1] - fy0 + oy0)) for m, p in final.items()}
    after = quality(objs, wires, final)
    ok = after['score'] < before['score'] * 0.85
    log['layout'].append(f'{where}: crossings {before["crossings"]} -> {after["crossings"]}, '
                         f'overlaps {before["overlaps"]} -> {after["overlaps"]} '
                         + ('APPLIED' if ok else 'kept original (no clear improvement)'))
    if ok:
        for m, (x, y) in final.items():
            b = objs[m]['bounds']
            dx, dy = x - b[0], y - b[1]
            if dx or dy:
                shift_object(objs[m]['chunk'], dx, dy)
    return ok


def _gap(a, b):
    dx = max(0, max(a[0], b[0]) - min(a[0] + a[2], b[0] + b[2]))
    dy = max(0, max(a[1], b[1]) - min(a[1] + a[3], b[1] + b[3]))
    return math.hypot(dx, dy)


# ---------------------------------------------------------------- driver
def process(doc, where, is_main, layout=True):
    remove_orphan_groups(doc, where)
    # clusters first (bottom-up), so their hooks can be named from the outside
    for o in objects_chunk(doc).children('Object'):
        c = container(o)
        if c is None:
            continue
        cd = c.item('ClusterDocument')
        if cd is None:
            continue
        blob = cd.value
        try:
            inner = R.parse(blob)
            compressed = True
        except zlib.error:
            inner = R.parse(blob, compressed=False)
            compressed = False
        name = (c.get('NickName') or c.get('Name') or 'cluster').strip()
        sub_where = f'{where} / {name}'
        name_hooks(inner, o, sub_where)
        process(inner, sub_where, False, layout)
        raw = R.serialise(inner)
        cd.value = R.deflate(raw) if compressed else raw
    fix_spelling(doc, where)
    if layout and not is_main:
        layout_doc(doc, where)


def main():
    src = sys.argv[1]
    dst = sys.argv[2] if len(sys.argv) > 2 else os.path.splitext(src)[0] + '_tidy.gh'
    if os.path.abspath(src) == os.path.abspath(dst):
        sys.exit('Refusing to overwrite the input file.')
    root = R.read_file(src)
    process(root, 'Main canvas', True)
    R.write_file(root, dst)
    print(f'Wrote {dst}\n')
    for k in ('orphan groups', 'cluster hooks', 'spelling', 'layout'):
        entries = list(dict.fromkeys(log[k]))
        print(f'== {k} ({len(entries)})')
        for e in entries:
            print('  ', e)
        print()
    from gh_verify import verify
    verify(src, dst)


if __name__ == '__main__':
    main()
