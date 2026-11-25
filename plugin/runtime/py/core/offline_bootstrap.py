# -*- coding: utf-8 -*-
"""Offline escape hatch — plugin capabilities keep working when the backend is down (official version, replacing the hand-rolled 15 lines).

The situation: as soon as the backend dies, headless/job/do are all dead; the user can only hand-roll the dsh_rt_kernel module inside blender.exe -b
and then import runtime/py/assembly/vehicle.py + runtime/py/core/audit.py to get the capabilities back. This file is the official version of those 15 lines.

Two ways to use it (neither needs the backend, neither needs KERNEL_BOOTSTRAP):

    # ① run it directly in Blender (GUI or -b both work)
    blender -b --factory-startup --python runtime/py/core/offline_bootstrap.py -- vehicle audit qc

    # ② inside your own script
    import offline_bootstrap as ob
    ns = ob.boot(["vehicle", "audit", "qc"])      # build the kernel + inject kit + load modules by name
    veh = ns["kapi"]("vehicle")                    # → module API (a dict, directly callable)
    print(veh("spec", {"type": "sports"}))

Convention: module names do not change (the preload contract does not change); implementation files are looked up only through
      runtime/py/<domain>/<name>.py as registered in runtime/py/modules.json (there is no flat runtime/<name>.py fallback any more).
      Once loaded, the API is mounted on K.dsh_<name>_api — **the same contract** as the online path.
"""
import json
import os
import sys
import types

# domain package layout (matches runtime/py/<domain>/)
_DOMAINS = ("core", "geometry", "assembly", "render", "export")


def _find_rt():
    """Locate runtime: env var first → the script's own directory → its runtime/ subdirectory → two levels up (the py/core layout).

    The return value is **the directory that contains kit.py**: normally <plugin>/runtime/py/core, in the old layout <plugin>/runtime.
    """
    here = os.path.dirname(os.path.abspath(__file__))
    cands = [os.environ.get("DSH_BLENDER_RUNTIME"), here,
             os.path.join(here, "runtime"),
             os.path.dirname(here),                    # runtime/py
             os.path.dirname(os.path.dirname(here)),   # runtime
             os.path.join(os.path.dirname(os.path.dirname(here)), "runtime")]
    for c in cands:
        if c and _kit_file(c):
            return c
    raise RuntimeError("cannot locate runtime (no kit.py in: %s) — set DSH_BLENDER_RUNTIME=<plugin>/runtime or pass runtime_dir=" % cands)


def _kit_file(rt):
    """kit.py under rt: the domain layout is py/core/kit.py, the old layout is kit.py."""
    for p in (os.path.join(rt, "kit.py"), os.path.join(rt, "py", "core", "kit.py")):
        if os.path.isfile(p):
            return p
    return None


def _runtime_root(rt):
    """The runtime root that holds kit.py (used for K.runtime_dir so kit.find_runtime_file can find the domain packages)."""
    if os.path.basename(rt) == "core" and os.path.basename(os.path.dirname(rt)) == "py":
        return os.path.dirname(os.path.dirname(rt))
    return rt


def _manifest_file(rt):
    """runtime/py/modules.json is the only list mapping module names → real files."""
    root = _runtime_root(rt)
    for p in (os.path.join(root, "py", "modules.json"), os.path.join(root, "modules.json")):
        if os.path.isfile(p):
            return p
    return None


def _load_manifest(rt):
    """Read the module manifest; return None when it is missing or corrupt (there is no flat-directory scan fallback any more)."""
    path = _manifest_file(rt)
    if path is None:
        return None
    try:
        with open(path, encoding="utf-8") as fh:
            raw = json.load(fh)
    except (OSError, ValueError):
        return None
    modules = raw.get("modules") if isinstance(raw, dict) else None
    if not isinstance(modules, dict) or not modules:
        return None
    return {str(k): str(v) for k, v in modules.items()}


def _module_dirs(rt):
    """The domain package directory list (now only used for error messages; module resolution goes by modules.json)."""
    root = _runtime_root(rt)
    return [os.path.join(root, "py", d) for d in _DOMAINS]


def _find_module(name, rt):
    """Find the .py by module name: only the single runtime/py/modules.json manifest is consulted (no flat fallback now).

    The manifest maps a module name to a domain name (core/geometry/...); an unregistered name, an invalid domain or a missing file
    all return None, and the caller reports a readable error that includes the module directories.
    """
    n = str(name or "").strip()
    if not n or any(ch not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_" for ch in n):
        return None
    manifest = _load_manifest(rt)
    if manifest is None or n not in manifest:
        return None
    domain = manifest[n]
    if domain not in _DOMAINS:
        return None
    declared = os.path.join(_runtime_root(rt), "py", domain, n + ".py")
    return declared if os.path.isfile(declared) else None


RT = _find_rt()


def _exec(path, ns, label):
    if not os.path.exists(path):
        raise RuntimeError("module file not found: %s (%s)" % (path, label))
    src = open(path, encoding="utf-8").read()
    exec(compile(src, path, "exec"), ns)


def _install_kernel_getattr(K):
    """Attach PEP 562 `__getattr__` to the kernel module: turn the bare AttributeError for "this module was not preloaded"
    into actionable guidance (measured feedback 2026-09-30: 4 agents independently got stuck on a missing `K.dsh_audit_api`).

    Only the `dsh_*_api` family of names is intercepted; every other attribute keeps native Python behaviour.
    """
    if hasattr(K, "__getattr__"):
        return K

    def _kernel_getattr(name, _K=K):
        if name.startswith("dsh_") and name.endswith("_api"):
            have = sorted(k[4:-4] for k in dir(_K)
                          if k.startswith("dsh_") and k.endswith("_api"))
            base = name[4:-4]
            raise AttributeError(
                "the kernel has no %s — module %r was not loaded. Loaded: %s. "
                "Headless: bring it with preload=%r; or look it up via K.dsh_kit.kapi(%r)."
                % (name, base, have or "(kit only)", base, base))
        raise AttributeError(name)

    K.__getattr__ = _kernel_getattr
    return K


def boot(modules=(), runtime_dir=None):
    """Build the kernel → inject the shared kernel kit → load modules by name; returns the namespace (with K and kapi).

    Names in modules keep the preload contract (e.g. "vehicle" / "qc") and need no path;
    runtime_dir may be the runtime root, py/core, or the runtime directory of the old layout.
    """
    rt = runtime_dir or RT
    K = sys.modules.get("dsh_rt_kernel")
    if K is None:
        K = types.ModuleType("dsh_rt_kernel")
        sys.modules["dsh_rt_kernel"] = K
    _install_kernel_getattr(K)
    # kit.find_runtime_file depends on K.runtime_dir; the old bootstrap never set it.
    setattr(K, "runtime_dir", _runtime_root(rt))
    if getattr(K, "dsh_kit", None) is None:
        _exec(_kit_file(rt), {"K": K, "__name__": "kit", "__file__": _kit_file(rt)}, "kit")
    ns: dict[str, object] = {"K": K}
    # v2.6.3 (regression fix): every module must be exec'd into its own namespace.
    # The old implementation stuffed all modules into one globals, and every module defines private helpers such as _num/_r/_j/_path,
    # so a later module shadowed the earlier ones (measured: assembly's _num(v) was overwritten by mesh_fix's _num(v,name,...),
    # and asm_export raised TypeError: _num() missing 1 required positional argument: 'name').
    # Matches the online kernel.preloadChunk convention: private names do not leak, only public names are merged back into the shared ns (compatible with older scripts).
    for name in modules:
        p = _find_module(name, rt)
        if p is None:
            raise RuntimeError("module %r not found (looked in: %s) — check the module name or runtime_dir"
                               % (name, os.pathsep.join(_module_dirs(rt))))
        mod_ns = {"K": K, "__name__": name, "__file__": p}
        _exec(p, mod_ns, name)
        ns.update({k: v for k, v in mod_ns.items() if not k.startswith("_")})
    ns["K"] = K

    def kapi(name):
        api = getattr(K, "dsh_%s_api" % name, None)
        if api is None:
            have = sorted(k[len("dsh_"):-len("_api")] for k in dir(K) if k.startswith("dsh_") and k.endswith("_api"))
            raise RuntimeError("module %s is not loaded; loaded: %s (bring it with boot([...]))" % (name, have))
        return api

    ns["kapi"] = kapi
    return ns


def _main(argv):
    # only treat "pure module names" as modules (the runner may stuff the script's own path into argv)
    names = [a for a in argv if not a.startswith("-") and "/" not in a and "\\" not in a and not a.endswith(".py")]
    ns = boot(names)
    loaded = sorted(k[len("dsh_"):-len("_api")] for k in dir(ns["K"]) if k.startswith("dsh_") and k.endswith("_api"))
    print("OFFLINE_BOOTSTRAP ok · loaded: " + (", ".join(loaded) or "(kit only)"))


if __name__ == "__main__":
    _main(sys.argv[1:])
