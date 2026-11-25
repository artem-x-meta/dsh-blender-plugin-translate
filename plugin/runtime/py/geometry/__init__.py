# -*- coding: utf-8 -*-
"""runtime.py.geometry — domain package (Phase E): geometry generation / repair / sculpting / blockout / contour fitting / face evaluation / surface algorithms

See __all__ for the module list. **This package is import-safe by itself**: it does not eagerly import submodules
(submodules need bpy/numpy and the shared kernel K.dsh_kit, so they load only when the Blender path is injected or
they are accessed explicitly).
Access a submodule: import runtime.py.geometry.kit  or  runtime.py.geometry.kit (lazy attribute).
"""
__all__ = ['geo', 'mesh_fix', 'sculpt', 'shapegen', 'shapesolve', 'faceeval', 'blockout', 'surface',
           'generator', 'uv_tools']


def __getattr__(name):
    # Lazy: both from runtime.py.geometry import kit and runtime.py.geometry.kit work;
    # importing the package does not pull in bpy.
    if name in __all__:
        import importlib
        mod = importlib.import_module(__name__ + "." + name)
        globals()[name] = mod
        return mod
    raise AttributeError("module %r has no attribute %r" % (__name__, name))
