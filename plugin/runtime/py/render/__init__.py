# -*- coding: utf-8 -*-
"""runtime.py.render — domain package (Phase E): viewport / QC / render guard / material / same-camera report / image tools / calibration / montage

See __all__ for the module list. **Importing this package is safe**: submodules are not eagerly imported
(submodules need bpy/numpy and the shared kernel K.dsh_kit, and only load on the Blender injection path or
on explicit access).
Access a submodule: import runtime.py.render.kit  or  runtime.py.render.kit (lazy attribute).
"""
__all__ = ['view', 'qc', 'qc_render', 'render_guard', 'material', 'visualreport', 'imgtools', 'calib', 'montage']


def __getattr__(name):
    # Lazy: both from runtime.py.render import kit / runtime.py.render.kit work;
    # does not pull in bpy when the package is imported.
    if name in __all__:
        import importlib
        mod = importlib.import_module(__name__ + "." + name)
        globals()[name] = mod
        return mod
    raise AttributeError("module %r has no attribute %r" % (__name__, name))
