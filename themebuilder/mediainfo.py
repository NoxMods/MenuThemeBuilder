"""Tiny dependency-free readers for .ogg and .bik headers."""
import struct


def read_ogg_info(path):
    """Return dict(duration_ms, rate, channels, codec). Raises ValueError if not a readable Ogg file."""
    with open(path, "rb") as f:
        head = f.read(4096)
        if head[:4] != b"OggS":
            raise ValueError("Not an Ogg file")
        nsegs = head[26]
        payload = head[27 + nsegs: 27 + nsegs + sum(head[27:27 + nsegs])]
        preskip = 0
        if payload[:7] == b"\x01vorbis":
            codec, channels = "vorbis", payload[11]
            rate = struct.unpack("<I", payload[12:16])[0]
        elif payload[:8] == b"OpusHead":
            codec, channels, rate = "opus", payload[9], 48000
            preskip = struct.unpack("<H", payload[10:12])[0]
        else:
            raise ValueError("Unsupported audio codec inside the Ogg container")
        f.seek(0, 2)
        size = f.tell()
        f.seek(max(0, size - 65536))
        tail = f.read()
    idx = tail.rfind(b"OggS")
    granule = -1
    while idx != -1:
        if tail[idx + 4] == 0:
            granule = struct.unpack("<q", tail[idx + 6: idx + 14])[0]
            if granule >= 0:
                break
        idx = tail.rfind(b"OggS", 0, idx)
    if granule < 0 or not rate:
        raise ValueError("Could not work out the length of this file")
    return {
        "duration_ms": int(round((granule - preskip) / rate * 1000)),
        "rate": rate, "channels": channels, "codec": codec,
    }


def read_bik_info(path):
    """Return dict(width, height, duration_ms) of a Bink video."""
    with open(path, "rb") as f:
        h = f.read(40)
    if h[:3] != b"BIK" or len(h) < 36:
        raise ValueError("Not a Bink (.bik) file")
    frames, = struct.unpack("<I", h[8:12])
    width, height, num, den = struct.unpack("<4I", h[20:36])
    dur = int(round(frames * den / num * 1000)) if num else 0
    return {"width": width, "height": height, "duration_ms": dur}
