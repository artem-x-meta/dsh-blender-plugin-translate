# -*- coding: utf-8 -*-
"""Assembly layer public facade — the implementation has been split into runtime/py/assembly/assembly_impl/.

The public contract is unchanged: headless preload="assembly", blender_rt_plan(op="asm_*"), the flat
runtime/assembly.py shim, and K.dsh_assembly_api still enter through this file. The implementation package keeps the original
function order and global names, so the 4k-line single file does not keep piling up at the domain package root.
"""
import importlib
import os
import sys

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

_impl = importlib.import_module("runtime.py._facade").load_impl("assembly", "assembly")
for _name in getattr(_impl, "__all__", ()):
    globals()[_name] = getattr(_impl, _name)
del _name
