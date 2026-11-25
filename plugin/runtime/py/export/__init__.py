# -*- coding: utf-8 -*-
"""runtime.py.export — domain package (Phase E): delivery / print check / Open3D external check

The module list is in __all__. **Importing this package is safe by itself**: submodules are not eagerly imported (they need
bpy/numpy and the shared kernel K.dsh_kit, so they load only on the Blender injection path or on explicit access).
Accessing a submodule: import runtime.py.export.kit  or  runtime.py.export.kit (lazy attribute).
"""
__all__ = ['deliver', 'printcheck', 'open3d_check']


def __getattr__(name):
    # Lazy: either from runtime.py.export import kit or runtime.py.export.kit works;
    # importing the package does not pull in bpy.
    if name in __all__:
        import importlib
        mod = importlib.import_module(__name__ + "." + name)
        globals()[name] = mod
        return mod
    raise AttributeError("module %r has no attribute %r" % (__name__, name))
