# -*- coding: utf-8 -*-
"""Public facade for motion inference/measurement/URDF/USDA export.

The public contract is unchanged: headless preload still loads this file by name, the flat
runtime/motion.py shim still points here, and K.dsh_motion_api still enters here. The implementation
has been split into runtime/py/core/motion_impl/ so the single file stops growing.
"""
import importlib
import os
import sys

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

_impl = importlib.import_module("runtime.py._facade").load_impl("core", "motion")
for _name in getattr(_impl, "__all__", ()):
    globals()[_name] = getattr(_impl, _name)
del _name
