# -*- coding: utf-8 -*-
"""Visual report public facade.

The public contract is unchanged: headless preload still loads this file by name, the flat runtime/visualreport.py shim
and K.dsh_visualreport_api still enter through this file. The implementation has been split into
runtime/py/render/visualreport_impl/ to keep a single file from growing further.
"""
import importlib
import os
import sys

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

_impl = importlib.import_module("runtime.py._facade").load_impl("render", "visualreport")
for _name in getattr(_impl, "__all__", ()):
    globals()[_name] = getattr(_impl, _name)
del _name
