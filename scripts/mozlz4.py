"""Minimal, dependency-free reader/writer for Mozilla's mozlz4 files
(magic b"mozLz40\\0" + uint32 LE decompressed size + raw LZ4 block)."""
import json
import struct
from pathlib import Path

MAGIC = b"mozLz40\0"


def lz4_block_decompress(src: bytes, size: int) -> bytes:
    out = bytearray()
    i, n = 0, len(src)
    while i < n:
        token = src[i]; i += 1
        lit = token >> 4
        if lit == 15:
            while True:
                b = src[i]; i += 1; lit += b
                if b != 255:
                    break
        out += src[i:i + lit]; i += lit
        if i >= n:
            break
        off = src[i] | (src[i + 1] << 8); i += 2
        mlen = (token & 15) + 4
        if (token & 15) == 15:
            while True:
                b = src[i]; i += 1; mlen += b
                if b != 255:
                    break
        start = len(out) - off
        for k in range(mlen):  # byte-wise: overlapping copies are legal
            out.append(out[start + k])
    if len(out) != size:
        raise ValueError(f"lz4: expected {size} bytes, got {len(out)}")
    return bytes(out)


def lz4_block_compress_literals(data: bytes) -> bytes:
    """Valid LZ4 block made of a single literal run (no compression).
    Firefox decodes it fine; files are just ~same size as the JSON."""
    n = len(data)
    if n < 15:
        return bytes([n << 4]) + data
    hdr = bytearray([0xF0])
    rest = n - 15
    while rest >= 255:
        hdr.append(255); rest -= 255
    hdr.append(rest)
    return bytes(hdr) + data


def read(path) -> dict:
    raw = Path(path).read_bytes()
    if raw[:8] != MAGIC:
        raise ValueError(f"not mozlz4: {path}")
    size = struct.unpack("<I", raw[8:12])[0]
    return json.loads(lz4_block_decompress(raw[12:], size))


def write(path, obj) -> None:
    data = json.dumps(obj, separators=(",", ":")).encode()
    Path(path).write_bytes(MAGIC + struct.pack("<I", len(data)) + lz4_block_compress_literals(data))


if __name__ == "__main__":
    import sys
    print(json.dumps(read(sys.argv[1]), indent=1))
