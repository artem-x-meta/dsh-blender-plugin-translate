# -*- coding: utf-8 -*-
"""Mesh audit public facade — the implementation has moved to runtime/py/core/audit_impl/.

The public contract is unchanged: headless preload="audit", blender_rt_plan(op="audit_*") and K.dsh_audit_api still
enter through this file. The original file was 3.2k lines; it is split by mesh/connectivity/drift/measurement/
overlap and interpenetration/API so a single file does not keep growing.
"""
import importlib
import os
import sys

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

_impl = importlib.import_module("runtime.py._facade").load_impl("core", "audit")
for _name in getattr(_impl, "__all__", ()):
    globals()[_name] = getattr(_impl, _name)
del _name
