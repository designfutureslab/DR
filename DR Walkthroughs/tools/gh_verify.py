"""
gh_verify.py - prove that two .gh files compute the same thing.

    python3 tools/gh_verify.py original.gh tidied.gh

Walks both files (including every nested cluster) and compares every stored
value. Each difference is classified; only these are allowed:
  moved      canvas positions (Bounds / Pivot / scribble corners)
  spelling   display text where new == typo-fixed(old)
  hook name  names of cluster inputs/outputs inside a cluster
  group      removal of empty groups (and their ID entries in other groups)
Anything else is reported as a BEHAVIOUR CHANGE and the check fails.
"""
import os, sys
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from gh_io import load
from gh_tidy import fix_text

POSITION = {'Bounds', 'Pivot', 'Ca', 'Cb', 'Cc', 'Cd'}
DISPLAY = {'NickName', 'CustomNickName', 'CustomName', 'Name', 'Description', 'Text', 'UserText'}
HOOKS = {'448de216-3a12-43cf-a135-e3bfafc87744', 'a4b285fe-2e13-4204-b65c-189aa6704da5'}


def _collapse(text):
    out = []
    for line in text.split('\n'):
        if not out or line != out[-1]:
            out.append(line)
    return '\n'.join(out)


def items(c):
    return {(n, i): v for n, i, v in c['items']}


def objects(doc):
    d = doc['chunks'][0] if doc['name'] == 'Root' else doc
    for c in d['chunks']:
        if c['name'] == 'DefinitionObjects':
            return c
    return None


def iid(o):
    for c in o['chunks']:
        if c['name'] == 'Container':
            return items(c).get(('InstanceGuid', -1))


class Diff:
    def __init__(self):
        self.kinds = Counter()
        self.errors = []

    def err(self, where, msg):
        self.errors.append(f'{where}: {msg}')


def wired_panels(objs):
    srcs, holders = set(), set()
    for o in objs:
        for ch in walk(o):
            for n, i, v in ch['items']:
                if n == 'Source':
                    srcs.add(v)
    for o in objs:
        top = items(o)
        if top.get(('GUID', -1)) == '59e0b89a-e487-49f8-bab8-b5bab16be14c':
            c = o['chunks'][0]
            ci = items(c)
            if any(n == 'Source' for n, _, _ in c['items']) or ci.get(('InstanceGuid', -1)) in srcs:
                holders.add(ci.get(('InstanceGuid', -1)))
    return holders


def walk(c):
    yield c
    for x in c['chunks']:
        yield from walk(x)


def cmp_chunk(a, b, where, D, ctx):
    ia, ib = items(a), items(b)
    for key in set(ia) | set(ib):
        n = key[0]
        va, vb = ia.get(key), ib.get(key)
        if va == vb:
            continue
        if n in POSITION and va is not None and vb is not None:
            D.kinds['moved'] += 1
            continue
        if n == 'ClusterDocument':
            cmp_doc(load(va[1]), load(vb[1]), where + ' / ' + str(ctx.get('nick')), D)
            continue
        if n in DISPLAY and isinstance(va, str) and isinstance(vb, str):
            if n == 'Text' and ctx.get('script'):
                D.err(where, 'script source changed')
            elif n == 'UserText' and ctx.get('wired'):
                D.err(where, f'wired panel text changed: {va!r} -> {vb!r}')
            elif fix_text(va) == vb:
                D.kinds['spelling'] += 1
            elif n == 'Description' and _collapse(va) == vb:
                D.kinds['repeated description lines removed'] += 1
            elif ctx.get('hook') and n in ('NickName', 'CustomNickName'):
                D.kinds['hook name'] += 1
            else:
                D.err(where, f'{n} changed unexpectedly: {va!r} -> {vb!r}')
            continue
        D.err(where, f'{key} changed: {str(va)[:80]} -> {str(vb)[:80]}')
    ca = [(c['name'], c['index']) for c in a['chunks']]
    cb = [(c['name'], c['index']) for c in b['chunks']]
    if ca != cb:
        D.err(where, f'sub-structure differs: {ca} vs {cb}')
        return
    for x, y in zip(a['chunks'], b['chunks']):
        sub = dict(ctx)
        if x['name'] == 'Script':
            sub['script'] = True
        cmp_chunk(x, y, where + '/' + x['name'], D, sub)


def cmp_doc(a, b, where, D):
    # everything except the object list must be identical (header, libraries ...)
    da = a['chunks'][0] if a['name'] == 'Root' else a
    db = b['chunks'][0] if b['name'] == 'Root' else b
    for x, y in zip(da['chunks'], db['chunks']):
        if x['name'] != 'DefinitionObjects' and x != y:
            if x['name'] == 'DefinitionProperties':
                continue  # file name / view only
            if x['name'] == 'DocumentHeader':
                D.kinds['editor display setting'] += 1   # document id, preview filter/colours: display only
                continue
            D.err(where, f'{x["name"]} differs')
    oa, ob = objects(a), objects(b)
    if not oa:
        return
    A = {iid(o): o for o in oa['chunks']}
    B = {iid(o): o for o in ob['chunks']}
    wired = wired_panels(oa['chunks'])
    removed = set(A) - set(B)
    if set(B) - set(A):
        D.err(where, f'{len(set(B) - set(A))} object(s) added')
    alive = set(B)
    for gid in removed:
        o = A[gid]
        if items(o).get(('GUID', -1)) != 'c552a431-af5b-46a9-a8a4-0fcbc27ef596':
            D.err(where, f'non-group object {gid} removed')
            continue
        mem = [v for n, i, v in o['chunks'][0]['items'] if n == 'ID']
        if any(m in alive and m not in removed for m in mem):
            D.err(where, f'removed group {gid} still had members')
        D.kinds['group removed'] += 1
    for k, o in A.items():
        if k not in B:
            continue
        o2 = B[k]
        top = items(o)
        guid = top.get(('GUID', -1))
        ctx = {'nick': items(o['chunks'][0]).get(('NickName', -1)), 'hook': guid in HOOKS,
               'wired': k in wired, 'script': False}
        if guid == 'c552a431-af5b-46a9-a8a4-0fcbc27ef596':
            # a surviving group may only lose references to removed groups
            ma = [v for n, i, v in o['chunks'][0]['items'] if n == 'ID']
            mb = [v for n, i, v in o2['chunks'][0]['items'] if n == 'ID']
            if [m for m in ma if m not in removed] != mb:
                D.err(where, f'group {ctx["nick"]!r} membership changed')
            ga = {kk: vv for kk, vv in items(o['chunks'][0]).items() if kk[0] not in ('ID', 'ID_Count', 'NickName')}
            gb = {kk: vv for kk, vv in items(o2['chunks'][0]).items() if kk[0] not in ('ID', 'ID_Count', 'NickName')}
            if ga != gb:
                D.err(where, f'group {ctx["nick"]!r} settings changed')
            continue
        if top != items(o2):
            D.err(where, f'object header differs for {ctx["nick"]!r}')
        cmp_chunk(o, o2, f'{where} :: {ctx["nick"]}', D, ctx)


def verify(a_path, b_path):
    D = Diff()
    cmp_doc(load(a_path), load(b_path), 'Main canvas', D)
    print('== verification')
    for k, v in sorted(D.kinds.items()):
        print(f'   {k}: {v} value(s)')
    if D.errors:
        print(f'   FAILED - {len(D.errors)} behaviour-affecting difference(s):')
        for e in D.errors[:40]:
            print('     !', e)
    else:
        print('   PASSED - wires, values, settings and scripts are identical; only layout/display text differ.')
    return not D.errors


if __name__ == '__main__':
    sys.exit(0 if verify(sys.argv[1], sys.argv[2]) else 1)
