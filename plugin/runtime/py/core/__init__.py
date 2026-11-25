# -*- coding: utf-8 -*-
"""runtime.py.core — domain package (Phase E): shared kernel / contract / gate / transactions / runner / worker / planning / presets / pipeline / perf / motion / sweep / audit / offline bootstrap

The module list is in __all__. **This package itself is import-safe**: it does not eagerly import submodules (submodules need
bpy/numpy and the shared kernel K.dsh_kit, so they load only on the Blender injection path or on explicit access).
Access a submodule with: import runtime.py.core.kit  or  runtime.py.core.kit (lazy attribute).
"""
__all__ = ['kit', 'contract', 'gate', 'txn', 'runner', 'worker', 'planner', 'presets', 'pipeline', 'perf', 'evalharness', 'motion', 'sweep', 'audit', 'offline_bootstrap']


def __getattr__(name):
    # lazy: both from runtime.py.core import kit and runtime.py.core.kit work;
    # importing the package never pulls bpy in.
    if name in __all__:
        import importlib
        mod = importlib.import_module(__name__ + "." + name)
        globals()[name] = mod
        return mod
    raise AttributeError("module %r has no attribute %r" % (__name__, name))
