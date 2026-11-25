# -*- coding: utf-8 -*-
"""runtime.py.assembly — domain package (Phase E): assembly / clearance / vehicle / human / assembly feature data

See __all__ for the module list. **This package is import-safe on its own**: it does not eagerly import
submodules (submodules need bpy/numpy and the shared kernel K.dsh_kit, so they load only along the Blender
injection path or on explicit access).
Access submodules: import runtime.py.assembly.kit  or  runtime.py.assembly.kit (lazy attribute).
"""
__all__ = ['assembly', 'clearance', 'vehicle', 'human']


def __getattr__(name):
    # Lazy: both "from runtime.py.assembly import kit" and "runtime.py.assembly.kit" work;
    # importing the package never pulls in bpy.
    if name in __all__:
        import importlib
        mod = importlib.import_module(__name__ + "." + name)
        globals()[name] = mod
        return mod
    raise AttributeError("module %r has no attribute %r" % (__name__, name))
