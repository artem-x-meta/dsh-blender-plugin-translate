# -*- coding: utf-8 -*-
"""Image analysis / measurement public facade.

The public contract is unchanged: headless preload still loads this file by name, the flat runtime/imgtools.py shim and
K.dsh_imgtools_api still enter through this file. The implementation has moved to runtime/py/render/imgtools_impl/ so the single file stops growing.
"""
import importlib
import os
import sys

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

_impl = importlib.import_module("runtime.py._facade").load_impl("render", "imgtools")
for _name in getattr(_impl, "__all__", ()):
    globals()[_name] = getattr(_impl, _name)
del _name
