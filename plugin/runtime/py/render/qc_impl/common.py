# -*- coding: utf-8 -*-
"""DSH built-in QC (v0.7.0) — objective comparison of a reference image against a render: mask / IoU / per-row width profile / comparison sheet.

API is exposed as K.dsh_qc_api; the inner-loop measure preset is exposed as K.dsh_measure.
Prototyped from 7 scripts the plush-build session wrote for itself (profile/sheet/ref_analysis/ref_measure, 539 lines in total),
turning "rewrite it per project" into a general capability; the thresholds and fill logic keep their tuned defaults, all parameterised.

Only **objective geometry/contour comparison**; aesthetic judgement still belongs to the human/model (this boundary is stated in help).

Typical use:
    arr, alpha = K.dsh_qc_api["load"]("//ref/ref_all_views.png")      # path helpers come from K
    m = K.dsh_qc_api["mask"](arr)                                     # foreground mask
    print(K.dsh_qc_api["iou"](m, m2))
    r = K.dsh_qc_api["compare"](ref_path, [9,38,444,545], render_png, label="front")
    # as an objective function inside the inner loop (lower is better):
    #   ns["score"] = K.dsh_measure["silhouette_iou"]({"from":[0,-6,1],"look_at":[0,0,0.5]}, ref_path, [9,38,444,545])
"""
import bpy as bpy
import json as json
import math as math
import os
import struct
import time as time
import zlib

import numpy as np  # noqa: F401  # re-exported for the qc facade / import boundary



QC_VERSION = 5
PNG_MAGIC = bytes([137, 80, 78, 71, 13, 10, 26, 10])


import sys as _sys_kit
_KIT = getattr(_sys_kit.modules.get("dsh_rt_kernel"), "dsh_kit", None)
if _KIT is None:
    raise RuntimeError("qc needs the shared kernel K.dsh_kit (injected by KERNEL_BOOTSTRAP)")


_j = _KIT.j  # shared kernel (the original local implementation was deleted)
def _kernel():
    import sys
    return sys.modules.get("dsh_rt_kernel")


def _out_dir():
    K = _kernel()
    return getattr(K, "out_dir", None) or os.path.join(os.path.expanduser("~"), "dsh_out")


# ---------------------------------------------------------------- direct PNG write (bypasses image.pixels to avoid double gamma)

def _chunk(t, body):
    return struct.pack(">I", len(body)) + t + body + struct.pack(">I", zlib.crc32(t + body) & 4294967295)


def write_png(path, w, h, rgb_bytes):
    raw = bytearray()
    stride = w * 3
    for y in range(h):
        raw.append(0)
        raw += rgb_bytes[y * stride:(y + 1) * stride]
    png = (PNG_MAGIC + _chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
           + _chunk(b"IDAT", zlib.compress(bytes(raw), 6)) + _chunk(b"IEND", b""))
    with open(path, "wb") as f:
        f.write(png)
    return path



# ---------------------------------------------------------------- v0.8.10 pure-Python GIF decoding
def _gif_lzw(min_code, data, expected):
    """GIF LZW decoding (returns the index sequence)."""
    clear = 1 << min_code
    end = clear + 1
    code_size = min_code + 1
    table = [bytes([i]) for i in range(clear)] + [b"", b""]
    out = bytearray()
    prev = None
    bitpos = 0
    total = len(data) * 8
    while bitpos + code_size <= total:
        byte_i = bitpos >> 3
        chunk = int.from_bytes(data[byte_i:byte_i + 3].ljust(3, b"\x00"), "little")
        code = (chunk >> (bitpos & 7)) & ((1 << code_size) - 1)
        bitpos += code_size
        if code == clear:
            table = [bytes([i]) for i in range(clear)] + [b"", b""]
            code_size = min_code + 1
            prev = None
            continue
        if code == end:
            break
        if prev is None:
            entry = table[code]
        elif code < len(table):
            entry = table[code]
            table.append(prev + entry[:1])
        else:
            entry = prev + prev[:1]
            table.append(entry)
        out += entry
        if prev is not None and len(table) < 4096 and code_size < 12 and len(table) >= (1 << code_size):
            code_size += 1
        prev = entry
        if expected and len(out) >= expected:
            break
    return bytes(out[:expected]) if expected else bytes(out)


def _wp(path):
    """Path normalisation (WSL→Windows / backslash UNC) so a Blender-side open() can use it."""
    K = _kernel()
    if K is not None and hasattr(K, "win_path"):
        try:
            return K.win_path(path)
        except Exception:
            pass
    return str(path)




__all__ = [name for name in list(globals()) if not name.startswith("__")]
