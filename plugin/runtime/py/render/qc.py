# -*- coding: utf-8 -*-
"""Image QC metrics public facade.

The public contract is unchanged: headless preload still loads this file by name, the flat runtime/qc.py shim
still resolves, and K.dsh_qc_api still enters through this file. The implementation has been split into
runtime/py/render/qc_impl/ so the single file stops growing.
"""
import importlib
import os
import sys

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

_impl = importlib.import_module("runtime.py._facade").load_impl("render", "qc")
for _name in getattr(_impl, "__all__", ()):
    globals()[_name] = getattr(_impl, _name)
del _name
