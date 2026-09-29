"""
gh_optimise.py - targeted speed-ups for the DR drawing script.

    python3 tools/gh_optimise.py input.gh [output.gh]      (default: <input>_fast.gh)

Never overwrites the input. Each optimisation below is a small, explicit edit;
afterwards every difference between the two files is listed, so the change log
is produced by comparing the files, not by trusting this script.

Output-identical:
  1. disconnect the '.SCR preview' panel that displayed the whole robot program
  2. delete the unused third pen-holder cluster inside every tool builder
  3. toolpath preview: show polylines instead of exploding them into segments
  7. every copy of the tool builder ("DFL DR2 Tool") is replaced by the master
     copy used in Make Custom Tool (see gh_sync_clusters.py); they were already
     functionally identical, so this is output-identical and keeps them in step
  6. the two "DFL re-orient planes" passes now run on ONE plane (World XY); a
     single native Orient then applies the result to every path plane. Exactly
     equivalent maths (rotating a plane about its own axes = rotating XY, then
     orienting XY onto the plane), but the per-plane work drops from ~14
     operations to 1. All controls (angles, axes, Pen Tilt) still work.
Changes a default setting:
  4. Create program 'Step Size' 1 mm -> 5 mm (error checking / simulation resolution)
  5. path tolerance slider 0.1 mm -> 0.25 mm (fewer planes, still finer than a pen line)
"""
import os, sys, uuid, zlib

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import gh_raw as R
from gh_tidy import objects_chunk, container, obj_info, param_chunks, sources, remove_orphan_groups

STEP_SIZE = 5.0
TOLERANCE = 0.25
done = []


def each_doc(doc, path, fn):
    """Apply fn(path, doc) to a document and every cluster inside it (bottom-up rewrite)."""
    for o in objects_chunk(doc).children('Object'):
        c = container(o)
        if c is None or c.item('ClusterDocument') is None:
            continue
        cd = c.item('ClusterDocument')
        try:
            inner, comp = R.parse(cd.value), True
        except zlib.error:
            inner, comp = R.parse(cd.value, compressed=False), False
        each_doc(inner, path + [(c.get('NickName') or 'Cluster').strip()], fn)
        raw = R.serialise(inner)
        cd.value = R.deflate(raw) if comp else raw
    fn(path, doc)


def all_sources(doc):
    out = []
    for o in objects_chunk(doc).children('Object'):
        for ch in o.walk():
            out += [it for it in ch.items if it.name == 'Source']
    return out


def delete_object(doc, oid):
    oc = objects_chunk(doc)
    oc.chunks = [o for o in oc.chunks if not (o.name == 'Object' and container(o) and container(o).get('InstanceGuid') == oid)]
    for i, o in enumerate(oc.chunks):
        o.index = i
    oc.item('ObjectCount').value = len(oc.chunks)
    for o in oc.chunks:
        c = container(o)
        if c is None or c.item('ID_Count') is None:
            continue
        ids = [it for it in c.items if it.name == 'ID']
        keep = [it for it in ids if it.value != oid]
        if len(keep) != len(ids):
            for n, it in enumerate(keep):
                it.index = n
            c.items = [it for it in c.items if it.name != 'ID' or it in keep]
            c.item('ID_Count').value = len(keep)
    remove_orphan_groups(doc, 'optimise')


TEMPLATES = {}


def collect_templates(doc):
    """Find existing components to copy (so new objects use Grasshopper's own format)."""
    for o in objects_chunk(doc).children('Object'):
        c = container(o)
        if c is None:
            continue
        nm = o.get('Name')
        if nm in ('Orient', 'XY Plane') and nm not in TEMPLATES and not any(
                sources(p) for p in param_chunks(c)[0] if p.get('Name') in ('Origin',)):
            TEMPLATES[nm] = o
        if c.item('ClusterDocument') is not None:
            try:
                collect_templates(R.parse(c.item('ClusterDocument').value))
            except zlib.error:
                collect_templates(R.parse(c.item('ClusterDocument').value, compressed=False))


def clone_component(template, x, y):
    """Deep copy with fresh ids and no wires; returns (chunk, {param name: new id}, new object id)."""
    def cp(ch):
        return R.Chunk(ch.rawname, ch.index, [R.Item(i.rawname, i.index, i.type, i.payload) for i in ch.items],
                       [cp(c) for c in ch.chunks])
    o = cp(template)
    for ch in o.walk():
        for it in ch.items:
            if it.name == 'InstanceGuid':
                it.value = str(uuid.uuid4())
        if any(it.name == 'Source' for it in ch.items):
            ch.items = [it for it in ch.items if it.name != 'Source']
            ch.item('SourceCount').value = 0
    c = container(o)
    ins, outs = param_chunks(c)
    ids = {('in', p.get('Name')): p.get('InstanceGuid') for p in ins}
    ids.update({('out', p.get('Name')): p.get('InstanceGuid') for p in outs})
    b = c.child('Attributes').get('Bounds')
    from gh_tidy import shift_object
    shift_object(o, x - b[0], y - b[1])
    return o, ids, c.get('InstanceGuid')


def set_source(param_chunk, src_id):
    param_chunk.items = [it for it in param_chunk.items if it.name != 'Source']
    param_chunk.items.append(R.Item(R.enc_str('Source'), 0, 9, uuid.UUID(src_id).bytes_le))
    param_chunk.item('SourceCount').value = 1


def add_object(doc, o):
    oc = objects_chunk(doc)
    o.index = len(oc.chunks)
    oc.chunks.append(o)
    oc.item('ObjectCount').value = len(oc.chunks)


def merge_reorient(doc, where):
    objs, groups, wires = obj_info(doc)
    reo = [ob for ob in objs.values() if (ob['cont'].get('NickName') or '').strip() == 'DFL re-orient planes']
    if len(reo) != 2 or 'Orient' not in TEMPLATES or 'XY Plane' not in TEMPLATES:
        return
    outs = {r['outs'][0].get('InstanceGuid'): r for r in reo}
    first = next(r for r in reo if not (set(sources(r['ins'][0])) & set(outs)))
    second = next(r for r in reo if r is not first)
    if sources(second['ins'][0]) != [first['outs'][0].get('InstanceGuid')]:
        return
    planes_src = sources(first['ins'][0])
    final = second['outs'][0].get('InstanceGuid')
    consumers = [(ob, h) for ob in objs.values() for h in [ob['cont']] + ob['ins'] if final in sources(h)]
    if len(planes_src) != 1 or len(consumers) != 1:
        return
    fb, sb = first['cont'].child('Attributes').get('Bounds'), second['cont'].child('Attributes').get('Bounds')
    xy, xy_ids, _ = clone_component(TEMPLATES['XY Plane'], fb[0] - 90, fb[1] - 50)
    orient, o_ids, _ = clone_component(TEMPLATES['Orient'], sb[0] + sb[2] + 40, sb[1] + sb[3] + 30)
    xy_out = xy_ids[('out', 'Plane')]
    set_source(first['ins'][0], xy_out)                        # re-orient passes now work on World XY only
    oin = {p.get('Name'): p for p in param_chunks(container(orient))[0]}
    set_source(oin['Geometry'], final)                         # the rotated reference plane
    set_source(oin['Source'], xy_out)                          # from World XY ...
    set_source(oin['Target'], planes_src[0])                   # ... onto every path plane
    for ob, h in consumers:                                    # downstream now reads Orient's result
        set_source(h, o_ids[('out', 'Geometry')])
    add_object(doc, xy)
    add_object(doc, orient)
    done.append(f'{where}: re-orient passes now run once on World XY; one Orient applies them to all planes')


def output_ids(o):
    ins, outs = param_chunks(container(o))
    return {p.get('InstanceGuid') for p in outs}


def opt(path, doc):
    where = ' / '.join(['Main canvas'] + path)
    objs, groups, wires = obj_info(doc)
    used = {it.value for it in all_sources(doc)}

    # 1. the panel showing the entire generated robot code
    if not path:
        for i, ob in objs.items():
            c = ob['cont']
            if (c.get('NickName') or '').strip() == '.SCR preview' and sources(c):
                c.items = [it for it in c.items if it.name != 'Source']
                c.item('SourceCount').value = 0
                c.item('UserText').value = ('Robot code preview is disconnected to keep Grasshopper fast.\n'
                                            'To read the code, wire Create program > Code into this panel '
                                            '(expect lag with big drawings), then disconnect it again.')
                done.append(f'{where}: disconnected ".SCR preview" panel from Create program > Code')

    # 2. dead pen-holder cluster in the tool builder (outputs not used by anything)
    if path and path[-1] == 'DFL DR2 Tool':
        for i, ob in list(objs.items()):
            c = ob['cont']
            if c.item('ClusterDocument') is not None and not (output_ids(ob['chunk']) & used):
                delete_object(doc, i)
                done.append(f'{where}: deleted unused cluster "{(c.get("NickName") or "").strip()}" (its outputs went nowhere)')

    # 3. toolpath preview: skip exploding every polyline into segments
    if path and path[-1] == 'DR preview':
        exp = next((ob for ob in objs.values() if ob['chunk'].get('Name') == 'Explode'), None)
        if exp:
            ins, outs = exp['ins'], exp['outs']
            src = sources(ins[0])
            seg = outs[0].get('InstanceGuid')
            others = [p.get('InstanceGuid') for p in outs[1:]]
            if len(src) == 1 and not (set(others) & used):
                for it in all_sources(doc):
                    if it.value == seg:
                        it.value = src[0]
                delete_object(doc, exp['cont'].get('InstanceGuid'))
                done.append(f'{where}: preview now uses the polylines directly (removed Explode)')

    # 6. merge the two re-orient passes into a single Orient
    if path and path[-1] == 'DR Path Planning':
        merge_reorient(doc, where)

    # 4. Create program step size
    for ob in objs.values():
        if ob['chunk'].get('Name') != 'Create program':
            continue
        for p in ob['ins']:
            if p.get('Name') != 'Step Size' or sources(p):
                continue
            for ch in p.walk():
                it = ch.item('number')
                if it is not None and it.type == 6 and it.value < STEP_SIZE:
                    old = it.value
                    it.value = STEP_SIZE
                    done.append(f'{where}: Create program Step Size {old:g} mm -> {STEP_SIZE:g} mm')

    # 5. default path tolerance
    if not path:
        for ob in objs.values():
            if (ob['cont'].get('NickName') or '').strip() != 'DR Path Planning':
                continue
            for p in ob['ins']:
                if (p.get('NickName') or '').strip().lower() not in ('tolerance', 'tollerance'):
                    continue
                for s in sources(p):
                    sl = objs.get(s)
                    sc = sl and sl['cont'].child('Slider')
                    if sc and sc.get('Value') < TOLERANCE:
                        old = sc.get('Value')
                        sc.item('Value').value = TOLERANCE
                        if sc.get('Digits', 0) < 2:
                            sc.item('Digits').value = 2
                        done.append(f'{where}: path tolerance slider {old:g} mm -> {TOLERANCE:g} mm')


def main():
    src = sys.argv[1]
    dst = sys.argv[2] if len(sys.argv) > 2 else os.path.splitext(src)[0].replace('_tidy', '') + '_fast.gh'
    if os.path.abspath(src) == os.path.abspath(dst):
        sys.exit('Refusing to overwrite the input file.')
    root = R.read_file(src)
    collect_templates(root)
    each_doc(root, [], opt)
    import gh_sync_clusters as S
    S.sync(root, 'DFL DR2 Tool')
    done.extend('tool builder ' + r for r in S.report)
    R.write_file(root, dst)
    print(f'Wrote {dst}\n\nEdits made:')
    for d in done:
        print('  -', d)
    # independent check: list every difference between the files
    from gh_verify import Diff, cmp_doc
    from gh_io import load
    D = Diff()
    cmp_doc(load(src), load(dst), 'Main canvas', D)
    print('\nAll differences found by comparing the two files:')
    for k, v in sorted(D.kinds.items()):
        print(f'  {k}: {v}')
    for e in D.errors:
        print('  *', e)


if __name__ == '__main__':
    main()
