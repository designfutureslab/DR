"""
gh_extract.py - turn a Grasshopper .gh file into a plain JSON "model".

No Rhino / Grasshopper install needed: the .gh binary format (GH_IO) is read
directly by gh_io.py. The model contains, for the main canvas and for every
cluster (recursively):

  * objects   - components, params, sliders, panels, scribbles, value lists,
                toggles, buttons, scripts (with source), clusters ...
                each with canvas bounds, nickname, description, plugin,
                inputs/outputs (with their own bounds and internalised values)
  * wires     - source param -> target param
  * groups    - colour, name, members, computed bounds

Identical cluster definitions (e.g. the same popup cluster used 8 times) are
stored once and referenced by id.

Usage:  python3 gh_extract.py input.gh output.json
"""
import base64, hashlib, json, sys, os
from gh_io import load

GROUP = 'c552a431-af5b-46a9-a8a4-0fcbc27ef596'
SCRIBBLE = '7f5c6c55-f846-4a08-9c9a-cfdc285cc6fe'
PANEL = '59e0b89a-e487-49f8-bab8-b5bab16be14c'
SLIDER = '57da07bd-ecab-415d-9d86-af36d7073abc'
TOGGLE = '2e78987b-9dfb-42a2-8b76-3923ac8bd91a'
BUTTON = 'a8b97322-2d53-47cd-905e-b932c3ccd74e'
SWATCH = '9c53bac0-ba66-40bd-8154-ce9829b9db1a'
CLUSTER_IN = '448de216-3a12-43cf-a135-e3bfafc87744'
CLUSTER_OUT = 'a4b285fe-2e13-4204-b65c-189aa6704da5'
RELAY = 'b6236720-8d88-4289-93c3-ac4c99f9b97b'

BUILTIN_LIB = 'Grasshopper'


def items(chunk):
    return {n if i < 0 else f'{n}({i})': v for n, i, v in chunk['items']}


def child(chunk, name):
    for c in chunk['chunks']:
        if c['name'] == name:
            return c
    return None


def children(chunk, name):
    return [c for c in chunk['chunks'] if c['name'] == name]


def listed(it, key):
    """Collect Key(0), Key(1) ... into a list."""
    out, i = [], 0
    while f'{key}({i})' in it:
        out.append(it[f'{key}({i})'])
        i += 1
    return out


def argb(v):
    if isinstance(v, (tuple, list)) and v and v[0] == 'argb':
        return {'a': v[1], 'r': v[2], 'g': v[3], 'b': v[4]}
    return None


def rect(v):
    return [round(x, 1) for x in v] if v else None


def summarise_persistent(chunk):
    """Short, human readable version of internalised data on a param."""
    if not chunk:
        return None
    simple = ('number', 'string', 'boolean', 'integer', 'bool', 'int', 'double', 'text')
    vals = []
    for br in children(chunk, 'Branch'):
        for itm in br['chunks']:
            it = [(n, v) for n, i, v in itm['items'] if not n.startswith('null_') and n != 'TypeName']
            keys = [n for n, v in it]
            if len(it) == 1 and keys[0].lower() in simple:
                v = it[0][1]
                vals.append(round(v, 4) if isinstance(v, float) else v)
            elif it and all(isinstance(v, tuple) and len(v) in (2, 3, 9) and
                            all(isinstance(x, (int, float)) for x in v) for n, v in it):
                v = it[0][1]  # point / plane / domain
                vals.append([round(x, 3) for x in v])
            else:
                kind = 'referenced Rhino geometry' if any(k.lower().startswith('ref') for k in keys) \
                    else 'internalised geometry'
                vals.append(f'<{kind}>')
    if not vals:
        return None
    if all(isinstance(v, str) and v.startswith('<') for v in vals):
        return f'{vals[0][:-1]} x{len(vals)}>' if len(vals) > 1 else vals[0]
    if len(vals) > 12:
        return vals[:12] + [f'... ({len(vals)} items)']
    return vals if len(vals) > 1 else vals[0]


def read_param(p):
    it = items(p)
    attr = child(p, 'Attributes')
    at = items(attr) if attr else {}
    d = {
        'id': it.get('InstanceGuid'),
        'name': it.get('Name'),
        'nick': it.get('NickName'),
        'desc': it.get('Description'),
        'sources': listed(it, 'Source'),
        'bounds': rect(at.get('Bounds')),
        'access': {0: 'item', 1: 'list', 2: 'tree'}.get(it.get('Access', 0)),
        'optional': it.get('Optional'),
        'wire': it.get('WireDisplay', 0),
    }
    pd = summarise_persistent(child(p, 'PersistentData'))
    if pd is not None:
        d['value'] = pd
    for flag in ('Reverse', 'Flatten', 'Graft', 'Simplify'):
        if it.get(flag):
            d.setdefault('flags', []).append(flag.lower())
    if it.get('Mapping') == 1:
        d.setdefault('flags', []).append('flatten')
    elif it.get('Mapping') == 2:
        d.setdefault('flags', []).append('graft')
    return d


class Extractor:
    def __init__(self):
        self.docs = {}     # doc_id -> doc model
        self.libs = {}     # lib id -> name

    def objects_chunk(self, root):
        if root['name'] == 'Root':
            root = root['chunks'][0]
        return child(root, 'DefinitionObjects'), root

    def doc(self, root, title, raw=None):
        """Parse a document (main canvas or cluster). Returns doc id."""
        doc_id = 'main' if raw is None else 'c_' + hashlib.sha1(raw).hexdigest()[:10]
        if doc_id in self.docs:
            return doc_id
        self.docs[doc_id] = None  # reserve (guards recursion)
        objs_chunk, defn = self.objects_chunk(root)
        for lib in children(child(defn, 'GHALibraries') or {'chunks': []}, 'Library'):
            li = items(lib)
            if li.get('Id') and li['Id'] != '00000000-0000-0000-0000-000000000000':
                self.libs[li['Id']] = {'name': li.get('Name'), 'author': li.get('Author'),
                                       'version': li.get('Version')}
        props = items(child(defn, 'DefinitionProperties') or {'items': [], 'chunks': []})
        objects, groups = [], []
        for o in (objs_chunk['chunks'] if objs_chunk else []):
            ob = self.obj(o)
            if ob is None:
                continue
            (groups if ob['kind'] == 'group' else objects).append(ob)
        d = {'id': doc_id, 'title': title, 'file_name': props.get('Name'),
             'objects': objects, 'groups': groups}
        self.finish(d)
        self.docs[doc_id] = d
        return doc_id

    def obj(self, o):
        top = items(o)
        cont = child(o, 'Container')
        if cont is None:
            return None
        it = items(cont)
        attr = child(cont, 'Attributes')
        at = items(attr) if attr else {}
        guid = top.get('GUID')
        ob = {
            'id': it.get('InstanceGuid'),
            'type': top.get('Name'),
            'type_guid': guid,
            'lib': top.get('Lib'),
            'name': it.get('Name'),
            'nick': it.get('NickName'),
            'desc': it.get('Description'),
            'bounds': rect(at.get('Bounds')),
        }
        if it.get('Hidden'):
            ob['preview_off'] = True
        if it.get('Enabled') is False or it.get('Locked'):
            ob['disabled'] = True
        if it.get('IconDisplay') == 2 or 'IconOverride' in it:
            ob['icon_mode'] = True

        if guid == GROUP:
            col = argb(it.get('Colour'))
            ob.update(kind='group', colour=col, border=it.get('Border'),
                      members=listed(it, 'ID'))
            # Bifocals plug-in (and similar) creates invisible single-object
            # groups whose nickname is just the component's name as a label.
            ob['label_only'] = bool(col and col['a'] == 0)
            return ob
        if guid == SCRIBBLE:
            ca, cc = it.get('Ca'), it.get('Cc')
            ob.update(kind='scribble', text=it.get('Text'), size=it.get('Size'),
                      font=it.get('Font'), bold=it.get('Bold'))
            if ca and cc and not ob['bounds']:
                ob['bounds'] = rect((ca[0], ca[1], cc[0] - ca[0], cc[1] - ca[1]))
            return ob

        # floating parameter-ish objects
        ob['sources'] = listed(it, 'Source')
        ob['wire'] = it.get('WireDisplay', 0)
        pd = summarise_persistent(child(cont, 'PersistentData'))
        if pd is not None:
            ob['value'] = pd

        if guid == PANEL:
            pp = items(child(cont, 'PanelProperties') or {'items': [], 'chunks': []})
            ob.update(kind='panel', text=it.get('UserText'), colour=argb(pp.get('Colour')))
        elif guid == SLIDER:
            s = items(child(cont, 'Slider'))
            ob.update(kind='slider', min=s.get('Min'), max=s.get('Max'),
                      val=s.get('Value'), digits=s.get('Digits'))
        elif guid == TOGGLE:
            ob.update(kind='toggle', val=it.get('ToggleValue'))
        elif guid == BUTTON:
            ob.update(kind='button')
        elif guid == SWATCH:
            ob.update(kind='swatch', colour=argb(it.get('SwatchColor')))
        elif children(cont, 'ListItem'):
            opts = []
            for li in children(cont, 'ListItem'):
                l = items(li)
                opts.append({'name': l.get('Name'), 'expr': l.get('Expression'),
                             'selected': bool(l.get('Selected'))})
            ob.update(kind='valuelist', options=opts)
        elif guid == CLUSTER_IN:
            ob.update(kind='cluster_input')
        elif guid == CLUSTER_OUT:
            ob.update(kind='cluster_output')
        elif guid == RELAY:
            ob.update(kind='relay')
        else:
            ob['kind'] = 'param'

        # components: inputs / outputs
        ins, outs = [], []
        pdata = child(cont, 'ParameterData')
        if pdata:
            ins = [read_param(p) for p in children(pdata, 'InputParam')]
            outs = [read_param(p) for p in children(pdata, 'OutputParam')]
        ins += [read_param(p) for p in children(cont, 'param_input')]
        outs += [read_param(p) for p in children(cont, 'param_output')]
        if ins or outs or pdata:
            ob['kind'] = 'component'
            ob['inputs'], ob['outputs'] = ins, outs
            ob.pop('sources', None)

        script = child(cont, 'Script')
        if script:
            si = items(script)
            code = si.get('Text', '')
            try:
                code = base64.b64decode(code).decode('utf-8')
            except Exception:
                pass
            lang = items(child(script, 'LanguageSpec') or {'items': [], 'chunks': []})
            ob.update(kind='script', code=code,
                      language=(lang.get('Taxon', '').split('.')[-1] or 'script')
                      + ' ' + lang.get('Version', ''))
        elif 'ScriptSource' in it or 'CodeInput' in it:  # legacy script comps
            ob.update(kind='script', code=it.get('ScriptSource') or it.get('CodeInput'),
                      language='legacy')

        if 'ClusterDocument' in it:
            raw = it['ClusterDocument'][1]
            sub = load(raw)
            ob['kind'] = 'cluster'
            ob['doc'] = self.doc(sub, it.get('NickName') or it.get('Name'), raw)
            auth = child(cont, 'Author')
            if auth:
                ob['author'] = {k: v for k, v in items(auth).items() if isinstance(v, str) and v}
        return ob

    def finish(self, d):
        """Resolve wires and group bounds for one document."""
        by_id = {}
        param_owner = {}   # param guid -> (object, param dict or None)
        for ob in d['objects']:
            by_id[ob['id']] = ob
            param_owner[ob['id']] = (ob, None)
            for p in ob.get('inputs', []) + ob.get('outputs', []):
                param_owner[p['id']] = (ob, p)
        wires = []

        def add(targets_holder, tgt_obj, tgt_param):
            for s in targets_holder.get('sources', []):
                if s in param_owner:
                    so, sp = param_owner[s]
                    wires.append({'from': so['id'], 'from_param': sp['id'] if sp else None,
                                  'to': tgt_obj['id'], 'to_param': tgt_param['id'] if tgt_param else None,
                                  'display': targets_holder.get('wire', 0)})
        for ob in d['objects']:
            if 'sources' in ob:
                add(ob, ob, None)
            for p in ob.get('inputs', []):
                add(p, ob, p)
        d['wires'] = wires

        gmap = {g['id']: g for g in d['groups']}

        def gbounds(g, seen=()):
            xs = []
            for m in g['members']:
                if m in by_id and by_id[m]['bounds']:
                    xs.append(by_id[m]['bounds'])
                elif m in gmap and m not in seen:
                    b = gbounds(gmap[m], seen + (g['id'],))
                    if b:
                        xs.append(b)
            if not xs:
                return None
            x0 = min(b[0] for b in xs); y0 = min(b[1] for b in xs)
            x1 = max(b[0] + b[2] for b in xs); y1 = max(b[1] + b[3] for b in xs)
            return [x0, y0, x1 - x0, y1 - y0]
        for g in d['groups']:
            g['bounds'] = gbounds(g)
            # which member objects are *directly* in the group (resolve nested groups)
            g['member_objects'] = [m for m in g['members'] if m in by_id]
            g['member_groups'] = [m for m in g['members'] if m in gmap]

        bs = [o['bounds'] for o in d['objects'] if o.get('bounds')]
        if bs:
            x0 = min(b[0] for b in bs); y0 = min(b[1] for b in bs)
            x1 = max(b[0] + b[2] for b in bs); y1 = max(b[1] + b[3] for b in bs)
            d['bounds'] = [x0, y0, x1 - x0, y1 - y0]


def extract(path):
    root = load(path)
    ex = Extractor()
    ex.doc(root, os.path.splitext(os.path.basename(path))[0])
    # record where each cluster doc is used, for navigation
    for d in ex.docs.values():
        for ob in d['objects']:
            if ob['kind'] == 'cluster':
                ex.docs[ob['doc']].setdefault('used_in', []).append({'doc': d['id'], 'object': ob['id']})
    return {'source_file': os.path.basename(path), 'libraries': ex.libs, 'docs': ex.docs}


if __name__ == '__main__':
    m = extract(sys.argv[1])
    with open(sys.argv[2], 'w') as f:
        json.dump(m, f, indent=1)
    n = sum(len(d['objects']) for d in m['docs'].values())
    print(f"{len(m['docs'])} documents, {n} objects -> {sys.argv[2]}")
