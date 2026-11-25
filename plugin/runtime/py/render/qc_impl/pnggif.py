# -*- coding: utf-8 -*-
"""Split from qc.py; behavior preserved by the facade."""
from .common import *  # noqa: F401,F403

def _gif_first_frame(path):
    """GIF first frame → (h, w, 4) uint8 RGBA. Only common cases are supported (GCT/LCT, interlacing, transparent index)."""
    path = _wp(path)
    with open(path, "rb") as f:
        data = f.read()
    if data[:6] not in (b"GIF87a", b"GIF89a"):
        raise RuntimeError("not a GIF file")
    i = 6
    w, h = struct.unpack("<HH", data[i:i + 4]); i += 4
    flags, _bg, _asp = data[i], data[i + 1], data[i + 2]; i += 3
    gct = None
    if flags & 0x80:
        n = 1 << ((flags & 7) + 1)
        gct = np.frombuffer(data[i:i + n * 3], dtype=np.uint8).reshape(n, 3).copy(); i += n * 3
    trans_idx = None
    canvas = np.zeros((h, w, 4), dtype=np.uint8)
    while i < len(data):
        b = data[i]
        if b == 0x3B:                                     # trailer
            break
        if b == 0x21:                                     # extension
            label = data[i + 1]; i += 2
            if label == 0xF9 and i + 6 < len(data):       # graphic control
                # layout: 21 <blockSize=4> <packed> <delay:2> <transparentIdx> 00
                i += 1                                        # ← older versions missed this blockSize byte, which shifted everything after it
                packed = data[i]; i += 1
                i += 2                                        # delay
                tidx = data[i]; i += 1
                if packed & 0x01:
                    trans_idx = tidx
                while i < len(data) and data[i]:
                    i += 1 + data[i]
                i += 1
            else:
                while i < len(data) and data[i]:
                    i += 1 + data[i]
                i += 1
            continue
        if b == 0x2C:                                     # image descriptor
            i += 1
            left, top, iw, ih = struct.unpack("<HHHH", data[i:i + 8]); i += 8
            lflags = data[i]; i += 1
            lct = gct
            if lflags & 0x80:
                n2 = 1 << ((lflags & 7) + 1)
                lct = np.frombuffer(data[i:i + n2 * 3], dtype=np.uint8).reshape(n2, 3).copy(); i += n2 * 3
            interlaced = bool(lflags & 0x40)
            min_code = data[i]; i += 1
            chunks = bytearray()
            while i < len(data) and data[i]:
                ln = data[i]; i += 1
                chunks += data[i:i + ln]; i += ln
            i += 1
            idx = np.frombuffer(_gif_lzw(min_code, bytes(chunks), iw * ih), dtype=np.uint8).reshape(ih, iw)
            if interlaced:
                rows = np.zeros(ih, dtype=int)
                k = 0
                for start, step in ((0, 8), (4, 8), (2, 4), (1, 2)):
                    for r in range(start, ih, step):
                        rows[r] = k; k += 1
                idx = idx[rows]
            if lct is None:
                raise RuntimeError("GIF has no color palette")
            rgb = lct[np.clip(idx.astype(int), 0, len(lct) - 1)]
            alpha = np.full((ih, iw), 255, dtype=np.uint8)
            if trans_idx is not None:
                alpha[idx == trans_idx] = 0
            y0, x0 = top, left
            canvas[y0:y0 + ih, x0:x0 + iw, :3] = rgb[:max(0, min(ih, h - y0)), :max(0, min(iw, w - x0))]
            canvas[y0:y0 + ih, x0:x0 + iw, 3] = alpha[:max(0, min(ih, h - y0)), :max(0, min(iw, w - x0))]
            return canvas
        i += 1
    raise RuntimeError("no image frame found in the GIF")


def gif_to_png(path, out=None):
    """GIF first frame → PNG (emergency channel: use it to turn a GIF into a readable image when this machine has no PIL/pip/ffmpeg)."""
    arr = _gif_first_frame(path)
    h, w = arr.shape[0], arr.shape[1]
    rgb = np.ascontiguousarray(arr[:, :, :3]).tobytes()
    out = out or (os.path.splitext(_wp(path))[0] + "_frame0.png")
    # an absolute macOS/Linux path starting with / also counts as "already absolute", otherwise _wp would process it again
    out_s = str(out)
    _abs = (out_s[1:2] == ":" or out_s.startswith(chr(92) * 2) or out_s.startswith("/"))
    out = out if _abs else _wp(out)
    write_png(out, w, h, rgb)
    return _j({"ok": True, "path": out, "size": [w, h], "bytes": os.path.getsize(out),
               "note": "only the first frame is taken; the remaining GIF frames are not decoded"})
