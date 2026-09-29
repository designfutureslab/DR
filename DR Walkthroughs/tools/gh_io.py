import struct, zlib, uuid, sys, json

class R:
    def __init__(s, b): s.b=b; s.p=0
    def take(s,n): v=s.b[s.p:s.p+n]; s.p+=n; return v
    def i32(s): return struct.unpack('<i', s.take(4))[0]
    def u8(s): return s.take(1)[0]
    def str(s):
        n=0; sh=0
        while True:
            c=s.u8(); n|=(c&0x7f)<<sh; sh+=7
            if not c&0x80: break
        return s.take(n).decode('utf-8', 'replace')

def read_item(r):
    t=r.i32()
    if t==1: return r.u8()!=0
    if t==2: return r.u8()
    if t==3: return r.i32()
    if t==4: return struct.unpack('<q', r.take(8))[0]
    if t==5: return struct.unpack('<f', r.take(4))[0]
    if t==6: return struct.unpack('<d', r.take(8))[0]
    if t==7: r.take(16); return 'decimal'
    if t==8: return ('date', struct.unpack('<q', r.take(8))[0])
    if t==9: return str(uuid.UUID(bytes_le=r.take(16)))
    if t==10: return r.str()
    if t==20: n=r.i32(); return ('bytes', r.take(n))
    if t==21: n=r.i32(); return list(struct.unpack('<%dd'%n, r.take(8*n)))
    if t in (30,32): return struct.unpack('<2i', r.take(8))
    if t in (31,33): return struct.unpack('<2f', r.take(8))
    if t==34: return struct.unpack('<4i', r.take(16))
    if t==35: return struct.unpack('<4f', r.take(16))
    if t==36: v=struct.unpack('<I', r.take(4))[0]; return ('argb', (v>>24)&255,(v>>16)&255,(v>>8)&255,v&255)
    if t==37: n=r.i32(); return ('bitmap', r.take(n))
    if t==50: return struct.unpack('<2d', r.take(16))
    if t==51: return struct.unpack('<3d', r.take(24))
    if t==52: return struct.unpack('<4d', r.take(32))
    if t==60: return struct.unpack('<2d', r.take(16))
    if t==61: return struct.unpack('<4d', r.take(32))
    if t in (70,71): return struct.unpack('<6d', r.take(48))
    if t==72: return struct.unpack('<9d', r.take(72))
    if t==80: return struct.unpack('<3i', r.take(12))
    raise ValueError('unknown type %d at %d'%(t, r.p))

def read_chunk(r):
    name=r.str(); idx=r.i32()
    ni=r.i32(); nc=r.i32()
    items=[]
    for _ in range(ni):
        n=r.str(); i=r.i32(); items.append((n,i,read_item(r)))
    chunks=[read_chunk(r) for _ in range(nc)]
    return {'name':name,'index':idx,'items':items,'chunks':chunks}

def load(path_or_bytes):
    d=open(path_or_bytes,'rb').read() if isinstance(path_or_bytes,str) else path_or_bytes
    try:
        o=zlib.decompressobj(-15); d2=o.decompress(d)+o.flush()
    except zlib.error:
        d2=d
    return read_chunk(R(d2))

def dump(c, depth=0, out=sys.stdout, maxd=99):
    pad='  '*depth
    out.write(f"{pad}[{c['name']}{'('+str(c['index'])+')' if c['index']>=0 else ''}]\n")
    for n,i,v in c['items']:
        if isinstance(v,tuple) and v and v[0] in ('bytes','bitmap'): v=f"<{v[0]} {len(v[1])}>"
        s=repr(v)
        if len(s)>200: s=s[:200]+'...'
        out.write(f"{pad}  {n}{'('+str(i)+')' if i>=0 else ''} = {s}\n")
    if depth<maxd:
        for ch in c['chunks']: dump(ch, depth+1, out, maxd)

if __name__=='__main__':
    root=load(sys.argv[1])
    dump(root, out=open(sys.argv[2],'w'))
