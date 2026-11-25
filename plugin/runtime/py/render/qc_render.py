# -*- coding: utf-8 -*-
"""QC render public facade - the implementation has moved to runtime/py/render/qc_render_impl/.

The public contract is unchanged: headless preload="qc_render", blender_rt_plan(op="qc_render_*"),
the flat runtime/qc_render.py shim and K.dsh_qc_render_api still enter through this file. The original file was 3.4k lines,
split by view / lock / projection / device / per-part / main flow / self-test / dispatch so the single file stops growing.
"""
import importlib
import os
import sys

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

_impl = importlib.import_module("runtime.py._facade").load_impl("render", "qc_render")
for _name in getattr(_impl, "__all__", ()):
    globals()[_name] = getattr(_impl, _name)
del _name
