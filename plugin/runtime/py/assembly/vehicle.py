# -*- coding: utf-8 -*-
"""Vehicle modeling/loft/fit public facade.

The public contract is unchanged: headless preload still loads this file by name, the flat runtime/vehicle.py shim,
and K.dsh_vehicle_api still enters through this file. The implementation was split into runtime/py/assembly/vehicle_impl/ so that one file does not keep growing.
"""
import importlib
import os
import sys

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

_impl = importlib.import_module("runtime.py._facade").load_impl("assembly", "vehicle")
for _name in getattr(_impl, "__all__", ()):
    globals()[_name] = getattr(_impl, _name)
del _name
