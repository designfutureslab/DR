"""
gh_sync_clusters.py - keep copies of a cluster identical to one master copy.

Grasshopper embeds a full copy of a cluster in every place it is used, so a fix
made in one copy does not reach the others. This makes one copy the master and
writes it into every other cluster with the same name.

    python3 tools/gh_sync_clusters.py input.gh "DFL DR2 Tool" [output.gh]

The master is the copy closest to the main canvas (for the DR script: the tool
builder inside "Make Custom Tool"). Edit that one in Grasshopper, save, then run
this. A copy is only replaced if its inputs/outputs match the master's (same
internal hook ids), so the wiring outside each copy stays valid.
"""
import os, re, sys, zlib

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import gh_raw as R
from gh_tidy import objects_chunk, container

report = []


def _parse(blob):
    try:
        return R.parse(blob), True
    except zlib.error:
        return R.parse(blob, compressed=False), False


def _instances(doc, path, name, out):
    for o in objects_chunk(doc).children('Object'):
        c = container(o)
        if c is None or c.item('ClusterDocument') is None:
            continue
        nick = (c.get('NickName') or '').strip()
        if nick == name:
            out.append((path, o))
        inner, _ = _parse(c.item('ClusterDocument').value)
        _instances(inner, path + [nick], name, out)
    return out


def _hooks(o):
    pm = container(o).child('ParamMap')
    return {it.value for it in pm.items if it.name == 'Value'} if pm else set()


def collapse_repeats(text):
    """Grasshopper sometimes appends the same description line on every save."""
    out = []
    for line in text.split('\n'):
        if not out or line != out[-1]:
            out.append(line)
    return '\n'.join(out)


def _clean(doc):
    for ch in doc.walk():
        for it in ch.items:
            if it.name == 'ClusterDocument':
                inner, comp = _parse(it.value)
                _clean(inner)
                raw = R.serialise(inner)
                it.value = R.deflate(raw) if comp else raw
            elif it.name == 'Description' and it.type == R.T_STRING:
                v = it.value
                if collapse_repeats(v) != v:
                    it.value = collapse_repeats(v)


def sync(root, name):
    found = _instances(root, [], name, [])
    if len(found) < 2:
        report.append(f'"{name}": fewer than two copies, nothing to sync')
        return
    found.sort(key=lambda f: len(f[0]))
    mpath, master = found[0]
    mc = container(master)
    inner, comp = _parse(mc.item('ClusterDocument').value)
    _clean(inner)
    raw = R.serialise(inner)
    blob = R.deflate(raw) if comp else raw
    mhooks = _hooks(master)
    key = lambda path, o: (tuple(path), container(o).get('InstanceGuid'))
    targets = {key(p, o) for p, o in found}
    mkey = key(mpath, master)
    where = lambda p: ' / '.join(['Main canvas'] + p)
    report.append(f'master: "{name}" in {where(mpath)}')

    def visit(doc, path):
        for o in objects_chunk(doc).children('Object'):
            c = container(o)
            if c is None or c.item('ClusterDocument') is None:
                continue
            nick = (c.get('NickName') or '').strip()
            k = key(path, o)
            if k in targets:
                if k == mkey or _hooks(o) <= mhooks:
                    c.item('ClusterDocument').value = blob
                    if k != mkey:
                        report.append(f'synced copy in {where(path)}')
                else:
                    report.append(f'SKIPPED copy in {where(path)}: its inputs/outputs differ from the master')
                continue
            sub, sc = _parse(c.item('ClusterDocument').value)
            visit(sub, path + [nick])
            r = R.serialise(sub)
            c.item('ClusterDocument').value = R.deflate(r) if sc else r
    visit(root, [])


def main():
    src, name = sys.argv[1], sys.argv[2]
    dst = sys.argv[3] if len(sys.argv) > 3 else os.path.splitext(src)[0] + '_synced.gh'
    if os.path.abspath(src) == os.path.abspath(dst):
        sys.exit('Refusing to overwrite the input file.')
    root = R.read_file(src)
    sync(root, name)
    R.write_file(root, dst)
    print(f'Wrote {dst}')
    for r in report:
        print('  -', r)
    from gh_verify import verify
    verify(src, dst)


if __name__ == '__main__':
    main()
