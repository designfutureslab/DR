"""
gh_raw.py - lossless read/write of Grasshopper .gh files (GH_IO binary archives).

Unlike gh_io.py (which decodes values for reading), this keeps every item's
type code and raw bytes, so a file can be read, edited and written back with
everything we did not touch preserved byte-for-byte. Cluster documents embedded
inside the file are themselves compressed archives and are handled the same way.
"""
import struct, zlib

SIZES = {1: 1, 2: 1, 3: 4, 4: 8, 5: 4, 6: 8, 7: 16, 8: 8, 9: 16, 30: 8, 31: 8, 32: 8, 33: 8,
         34: 16, 35: 16, 36: 4, 50: 16, 51: 24, 52: 32, 60: 16, 61: 32, 70: 48, 71: 48, 72: 72, 80: 12}
T_STRING, T_POINTF, T_RECTF, T_BYTES = 10, 31, 35, 20


def enc_str(s):
    b = s.encode('utf-8')
    n, out = len(b), bytearray()
    while True:
        c = n & 0x7f
        n >>= 7
        out.append(c | (0x80 if n else 0))
        if not n:
            break
    return bytes(out) + b


class Item:
    __slots__ = ('rawname', 'index', 'type', 'payload')

    def __init__(self, rawname, index, type_, payload):
        self.rawname, self.index, self.type, self.payload = rawname, index, type_, payload

    @property
    def name(self):
        return _dec_str(self.rawname)

    @property
    def value(self):
        t, p = self.type, self.payload
        if t == T_STRING:
            return _dec_str(p)
        if t == T_POINTF:
            return struct.unpack('<2f', p)
        if t == T_RECTF:
            return struct.unpack('<4f', p)
        if t == 3:
            return struct.unpack('<i', p)[0]
        if t == 6:
            return struct.unpack('<d', p)[0]
        if t == 1:
            return p[0] != 0
        if t == 9:
            import uuid
            return str(uuid.UUID(bytes_le=p))
        if t == 36:
            v = struct.unpack('<I', p)[0]
            return (v >> 24) & 255, (v >> 16) & 255, (v >> 8) & 255, v & 255
        if t == T_BYTES:
            return p[4:]
        return p

    @value.setter
    def value(self, v):
        t = self.type
        if t == T_STRING:
            self.payload = enc_str(v)
        elif t == T_POINTF:
            self.payload = struct.pack('<2f', *v)
        elif t == T_RECTF:
            self.payload = struct.pack('<4f', *v)
        elif t == 3:
            self.payload = struct.pack('<i', v)
        elif t == 6:
            self.payload = struct.pack('<d', v)
        elif t == 9:
            import uuid
            self.payload = uuid.UUID(v).bytes_le
        elif t == 1:
            self.payload = bytes([1 if v else 0])
        elif t == T_BYTES:
            self.payload = struct.pack('<i', len(v)) + v
        else:
            raise TypeError(f'setting type {t} not supported')


def _dec_str(raw):
    n = sh = i = 0
    while True:
        c = raw[i]
        i += 1
        n |= (c & 0x7f) << sh
        sh += 7
        if not c & 0x80:
            break
    return raw[i:i + n].decode('utf-8', 'replace')


class Chunk:
    __slots__ = ('rawname', 'index', 'items', 'chunks')

    def __init__(self, rawname, index, items, chunks):
        self.rawname, self.index, self.items, self.chunks = rawname, index, items, chunks

    @property
    def name(self):
        return _dec_str(self.rawname)

    def item(self, name, index=-1):
        for it in self.items:
            if it.index == index and it.name == name:
                return it
        return None

    def get(self, name, default=None, index=-1):
        it = self.item(name, index)
        return it.value if it else default

    def child(self, name):
        for c in self.chunks:
            if c.name == name:
                return c
        return None

    def children(self, name):
        return [c for c in self.chunks if c.name == name]

    def walk(self):
        yield self
        for c in self.chunks:
            yield from c.walk()


class _R:
    def __init__(self, b):
        self.b, self.p = b, 0

    def i32(self):
        v = struct.unpack_from('<i', self.b, self.p)[0]
        self.p += 4
        return v

    def rawstr(self):
        st = self.p
        n = sh = 0
        while True:
            c = self.b[self.p]
            self.p += 1
            n |= (c & 0x7f) << sh
            sh += 7
            if not c & 0x80:
                break
        self.p += n
        return self.b[st:self.p]


def _payload(r, t):
    st = r.p
    if t in SIZES:
        r.p += SIZES[t]
    elif t == T_STRING:
        r.rawstr()
    elif t in (20, 37, 21):
        n = r.i32()          # (read first: i32() advances the cursor)
        r.p += n * (8 if t == 21 else 1)
    else:
        raise ValueError(f'unknown GH_IO type {t} at byte {r.p}')
    return r.b[st:r.p]


def _chunk(r):
    name = r.rawstr()
    idx, ni, nc = r.i32(), r.i32(), r.i32()
    items = []
    for _ in range(ni):
        n = r.rawstr()
        i, t = r.i32(), r.i32()
        items.append(Item(n, i, t, _payload(r, t)))
    return Chunk(name, idx, items, [_chunk(r) for _ in range(nc)])


def parse(data, compressed=True):
    raw = zlib.decompress(data, -15) if compressed else data
    r = _R(raw)
    c = _chunk(r)
    if r.p != len(raw):
        raise ValueError('trailing bytes after archive')
    return c


def serialise(c):
    out = [c.rawname, struct.pack('<iii', c.index, len(c.items), len(c.chunks))]
    for it in c.items:
        out += [it.rawname, struct.pack('<ii', it.index, it.type), it.payload]
    out += [serialise(x) for x in c.chunks]
    return b''.join(out)


def deflate(raw):
    co = zlib.compressobj(9, zlib.DEFLATED, -15)
    return co.compress(raw) + co.flush()


def read_file(path):
    with open(path, 'rb') as f:
        return parse(f.read())


def write_file(root, path):
    with open(path, 'wb') as f:
        f.write(deflate(serialise(root)))
