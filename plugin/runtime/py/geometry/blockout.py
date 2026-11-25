# -*- coding: utf-8 -*-
"""blockout modeling/export/presentation public facade.

The public contract is unchanged: headless preload still loads this file by file name, the flat runtime/blockout.py shim,
and K.dsh_blockout_api still enters through this file. The implementation has been split into runtime/py/geometry/blockout_impl/ so the single file stops growing.
"""
import importlib
import os
import sys

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

_impl = importlib.import_module("runtime.py._facade").load_impl("geometry", "blockout")
for _name in getattr(_impl, "__all__", ()):
    globals()[_name] = getattr(_impl, _name)
del _name
