/**
 * Paths and constants (moved out of engine.mjs)
 *
 * Absolute / cross-OS paths, temp directories, the addon-side command directory, and the PATH_HELPERS used by KERNEL_BOOTSTRAP.
 * engine.mjs named-imports them and re-exports them unchanged ⇒ the outside surface is byte-for-byte the same (compared by tmp/snap.mjs / snap_norm.mjs).
 */
import { createHash } from 'node:crypto';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { CFG, PATHS, IS_WIN, IS_MAC, wslToWin } from './config.js';
/** Same directory as engine.mjs (runtime/) */
export const HERE = path.dirname(fileURLToPath(import.meta.url));
/** Python asset root: in the source tree = runtime/; in a build = the package-root runtime/ (two levels up from lib/runtime/*.js) */
export const PY_ROOT = (() => {
    if (fs.existsSync(path.join(HERE, 'py')))
        return HERE;
    const built = path.resolve(HERE, '..', '..', 'runtime');
    if (fs.existsSync(path.join(built, 'py')))
        return built;
    return HERE;
})();
export const ADDRESS = { host: CFG.addonHost, port: CFG.addonPort };
export const WIN_TMP = CFG.workDirWin;
export const WSL_TMP = CFG.workDirWsl;
export const LIVE_PNG_WIN = PATHS.livePngWin;
export const LIVE_PNG_WSL = PATHS.livePngWsl;
/**
 * Express a host-side path in the form the **Blender process side** uses.
 * Windows: path.win32.join (backslashes + drive letter); WSL: wslToWin; macOS: identity (same machine, same OS).
 * macOS support: the previously scattered path.win32.join produced garbage like \Users\... on the mac,
 * now it is collected here so nothing is missed again.
 */
export function blenderJoin(...parts) {
    if (IS_MAC)
        return path.join(...parts);
    if (IS_WIN)
        return path.win32.join(...parts);
    return wslToWin(path.join(...parts));
}
function loadPyModuleManifest() {
    const file = path.join(PY_ROOT, 'py', 'modules.json');
    let raw;
    try {
        raw = JSON.parse(fs.readFileSync(file, 'utf8'));
    }
    catch (e) {
        throw new Error('failed to read the Python module manifest: ' + file + ' (' + String(e) + ')', { cause: e });
    }
    const parsed = raw;
    const domains = Array.isArray(parsed.domains) ? parsed.domains.map(String) : [];
    const modules = parsed.modules && typeof parsed.modules === 'object'
        ? parsed.modules
        : {};
    if (!domains.length || !Object.keys(modules).length) {
        throw new Error('malformed Python module manifest: ' + file);
    }
    return { version: Number(parsed.version) || 0, domains, modules };
}
const PY_MANIFEST = loadPyModuleManifest();
export const PY_DOMAINS = PY_MANIFEST.domains;
const PY_MODULE_DOMAIN = PY_MANIFEST.modules;
/** Public module name → runtime/py/<domain>/<name>.py (the sole registration source is modules.json). */
export function pyModuleFile(name) {
    const n = String(name == null ? '' : name)
        .trim()
        .replace(/\.py$/, '');
    const d = Object.prototype.hasOwnProperty.call(PY_MODULE_DOMAIN, n) ? PY_MODULE_DOMAIN[n] : null;
    if (!d)
        throw new Error('unknown runtime Python module: ' +
            n +
            ' (not registered in modules.json; available: ' +
            pyModuleNames().join(', ') +
            ')');
    return path.join(PY_ROOT, 'py', d, n + '.py');
}
/** All public module names (used to list them when a preload fails; does not vary with the filesystem). */
export function pyModuleNames() {
    return Object.keys(PY_MODULE_DOMAIN).sort();
}
export function pyModuleExists(name) {
    try {
        return fs.existsSync(pyModuleFile(name));
    }
    catch (e) {
        return false;
    }
}
/** Shared kernel (kit): the single implementation of JSON/API boilerplate, units, geometry, measurement and the receipt skeleton */
export const KIT_PATH = pyModuleFile('kit');
/** Geometry base (geo): the **mechanism layer** — boolean/hole/slot/mirror/array/extrude/loft/bevel/auto-smooth.
 *  Verbs only, no nouns (no shape defaults whatsoever); guaranteed present by KERNEL_BOOTSTRAP just like kit. */
export const GEO_PATH = pyModuleFile('geo');
export const RUNNER_PATH = pyModuleFile('runner');
export const PERF_PATH = pyModuleFile('perf');
export const VIEW_PATH = pyModuleFile('view');
/** Contract layer: component/connection registry, envelope/interference/interface validation, destructive gating, evidence ledger, three-state verdicts */
export const CONTRACT_PATH = pyModuleFile('contract');
/** Planner: object graph → diagnostics → compile to bpy → graph export */
export const PLANNER_PATH = pyModuleFile('planner');
export const WORKER_PATH = pyModuleFile('worker');
export const TXN_PATH = pyModuleFile('txn');
/** Built-in QC (v0.7.0): mask / IoU / profile / comparison images + inner-loop measure presets */
export const QC_PATH = pyModuleFile('qc');
/** Render harness (v0.8.8): auto framing + fixed three-point light + per-image jsonl timing + budget verdict */
export const QC_RENDER_PATH = pyModuleFile('qc_render');
/** Preset library (v0.8.2): saving / applying / exporting parameter combinations */
export const PRESET_PATH = pyModuleFile('presets');
/** Mesh audit (wired up in v0.9.0): audit_* prefixed ops go here.
 *  Before this, audit.py existed only on the preload channel, and the documented blender_rt_plan(op="audit_mesh") had no route at all. */
export const AUDIT_PATH = pyModuleFile('audit');
/** Montage (wired up in v0.9.0): the montage op goes here (evidence tier L2: cropped sheets of the few cells worth looking at) */
export const MONTAGE_PATH = pyModuleFile('montage');
/** Articulation / mechanisms (v0.9.0): joint measurement + sweep validation + URDF/USDA export (motion_* prefixed ops) */
export const MOTION_PATH = pyModuleFile('motion');
/** Delivery export (v0.9.0): unit-box normalisation + several OBJ/MTL groups + manifest(md5) (deliver_* prefixed ops) */
export const DELIVER_PATH = pyModuleFile('deliver');
/** Generator registry (v0.9.0 · #18, the lightweight Blender-native version of the code-modelling channel): now part of the geometry domain package. */
export const GENERATOR_PATH = pyModuleFile('generator');
/** Procedural sculpting (v0.9.6 · upstream integration): sculpt_* prefixed ops go here.
 *  Neither upstream project can sculpt procedurally (blend-ai says outright that it cannot simulate strokes; mcp-for-blender has no sculpting),
 *  so this module uses numpy displacement brushes + topology preparation + masking to turn "sculpting" into recomputable geometry operations. */
export const SCULPT_PATH = pyModuleFile('sculpt');
/** Mesh-repair loop (v0.9.6 · upstream integration): fix_* prefixed ops — audit only diagnoses, this is what treats. */
export const FIX_PATH = pyModuleFile('mesh_fix');
/** The set of four UV tools (v0.9.6 · upstream integration): now part of the geometry domain package. */
export const UV_PATH = pyModuleFile('uv_tools');
/** Manufacturing check (v0.9.6 · upstream integration): print_* prefixed ops (thin walls / overhang / shell / summary). */
export const PRINT_PATH = pyModuleFile('printcheck');
/** Sweep along a path (v0.9.6 · upstream integration): sweep_* prefixed ops (pipes/cables/tracks + bend radii computed before building). */
export const SWEEP_PATH = pyModuleFile('sweep');
/** Material node graphs (v0.9.6): material_* prefixed ops — measured at 2,732 node links / 204 scripts reinventing the wheel */
export const MATERIAL_PATH = pyModuleFile('material');
/** Render state tracking (v0.9.6): write a disk flag when a render starts, delete it when it ends; the backend decides busy by reading the file instantly */
export const RENDER_GUARD_PATH = pyModuleFile('render_guard');
/** Spec-driven gate package (v0.9.6 · field feedback #3): one spec runs every gate (three-state verdicts) */
export const GATE_PATH = pyModuleFile('gate');
/** Reference-image instruments (integration plan): measure into numbers / crop and zoom / draw back / diff */
export const IMG_PATH = pyModuleFile('imgtools');
/** Gate calibration suite: inject 8 defect classes and see how many the gates catch + a healthy-baseline comparison */
export const CALIB_PATH = pyModuleFile('calib');
/** Face proportion gate: landmarks → 6 dimensionless ratios → difference against classical / reference values */
export const FACE_PATH = pyModuleFile('faceeval');
/** Human base mesh (zero assets): joint coordinates + radii → Skin+Subsurf → a correctly proportioned dummy */
export const HUMAN_PATH = pyModuleFile('human');
/** Paired-clearance gate: rule-table-driven nearest distance + interpenetration verdict */
export const CLEARANCE_PATH = pyModuleFile('clearance');
/** Vehicle shell: longitudinal profile → lofted shell (analytic wheel arches) + proportion gate */
export const VEHICLE_PATH = pyModuleFile('vehicle');
/** General reference-image reconstruction method layer: category protocols + generic instruments/loft/fit/parting/revolve */
export const SHAPE_PATH = pyModuleFile('shapegen');
/** Pipeline: artefact registry + step orchestration */
export const PIPELINE_PATH = pyModuleFile('pipeline');
/** Assembly: manifest / all-to-all classification scan / merge / assembly gate */
export const ASSEMBLY_PATH = pyModuleFile('assembly');
/** Blockout: declarative blockout + 3 views + GLB export */
export const BLOCKOUT_PATH = pyModuleFile('blockout');
/** Same-camera QC visual report (verdict-first) */
export const VISUALREPORT_PATH = pyModuleFile('visualreport');
/** Headless multi-view silhouette fitting (analytic projection, no rendering) */
export const SHAPESOLVE_PATH = pyModuleFile('shapesolve');
/** Defect injection / baseline replay evaluation (evalharness) */
export const EVALHARNESS_PATH = pyModuleFile('evalharness');
/** Surface algorithm package: loft/sweep/patch/validate */
export const SURFACE_PATH = pyModuleFile('surface');
/**
 * The user's Blender config directory (where the GPU preference lives) — a headless process cannot read it by default, so Cycles silently falls back to CPU.
 * The shared build defaults to null (use the system default config); to inherit a config set DSH_BLENDER_USER_CONFIG / the blenderUserConfig option.
 */
export const USER_CONFIG_WIN = process.env.BLENDER_USER_CONFIG || CFG.blenderUserConfig || null;
export const USER_SCRIPTS_WIN = process.env.BLENDER_USER_SCRIPTS || CFG.blenderUserScripts || null;
/** GPU prelude: configure the Cycles device inside the headless process and print a DSH_GPU receipt (see README "GPU semantics") */
/**
 * Engine prelude (v0.8.0): default **EEVEE + ray tracing**, optionally cycles (OptiX device prelude) / keep (leave alone).
 * Why the default changed to EEVEE: (1) it is pure GPU rendering through the graphics backend (OPENGL / RTX 4060 on this machine),
 *   **it does not depend on "preferences" like compute_device_type** → in headless it will not silently fall back to CPU the way Cycles does;
 * (2) measured (360 objects / 350 meshes / 512×512 / 64 samples): EEVEE+RT warm-up frame **1.35 s** vs Cycles GPU **3.13 s** (2.3×);
 * (3) the cost: first-frame shader compilation ~16 s → for iteration use a blender_rt_worker hot session (compile once, then 1.35 s per frame).
 * The receipt marker stays DSH_GPU (for compatibility); it contains engine / backend / renderer / rt state.
 */
export const GPU_PRELUDE = [
    'def _dsh_engine_setup():',
    '    import bpy, json',
    '    mode = __DSH_ENGINE__',
    '    manual = __DSH_GPU_MANUAL__',
    '    info = {"mode": mode, "manual": manual}',
    '    try:',
    '        import gpu',
    '        info["backend"] = gpu.platform.backend_type_get()',
    '        info["renderer"] = gpu.platform.renderer_get()',
    '    except Exception as e:',
    '        info["backend"] = "n/a: %s" % str(e)[:60]',
    '    sc = bpy.context.scene',
    '    info["before"] = {"engine": sc.render.engine}',
    '    if mode == "keep":',
    '        info["ok"] = True',
    '        info["skipped"] = True',
    '        info["after"] = {"engine": sc.render.engine}',
    '        print("DSH_GPU " + json.dumps(info, ensure_ascii=False))',
    '        return',
    '    if mode == "cycles":',
    '        try:',
    '            prefs = bpy.context.preferences.addons["cycles"].preferences',
    '        except Exception as e:',
    '            info.update({"ok": False, "error": "no cycles prefs: %s" % e})',
    '            print("DSH_GPU " + json.dumps(info, ensure_ascii=False))',
    '            return',
    '        def snap():',
    '            try:',
    '                devs = [d.name for d in prefs.devices if d.use and d.type != "CPU"]',
    '            except Exception:',
    '                devs = []',
    '            return {"device_type": prefs.compute_device_type, "scene_device": getattr(sc.cycles, "device", None), "gpu_enabled": devs}',
    '        info["cycles_before"] = snap()',
    '        if info["cycles_before"]["device_type"] == "NONE" or not info["cycles_before"]["gpu_enabled"]:',
    '            chosen = None',
    '            errs = []',
    '            for t in ["OPTIX", "CUDA", "HIP", "ONEAPI", "METAL"]:',
    '                try:',
    '                    prefs.compute_device_type = t',
    '                    prefs.get_devices()',
    '                    if [d for d in prefs.devices if d.type != "CPU"]:',
    '                        for d in prefs.devices:',
    '                            d.use = (d.type != "CPU")',
    '                        chosen = t',
    '                        break',
    '                except Exception as e:',
    '                    errs.append("%s: %s" % (t, e))',
    '            info["tried"] = errs',
    '            info["configured"] = chosen',
    '            if not chosen:',
    '                info["error"] = "no GPU backend available (tried OPTIX/CUDA/HIP/ONEAPI/METAL)"',
    '        try:',
    '            sc.render.engine = "CYCLES"',
    '            if info.get("configured"):',
    '                sc.cycles.device = "GPU"',
    '        except Exception as e:',
    '            info["engine_set_err"] = str(e)[:80]',
    '        info["cycles_after"] = snap()',
    '        a = info["cycles_after"]',
    '        info["fell_back_to_cpu"] = bool(a["device_type"] == "NONE" or not a["gpu_enabled"])',
    '        info["ok"] = (not info["fell_back_to_cpu"]) or (not manual)',
    '        info["after"] = {"engine": sc.render.engine}',
    '        print("DSH_GPU " + json.dumps(info, ensure_ascii=False))',
    '        return',
    '    ee = getattr(sc, "eevee", None)',
    '    info["before"]["rt"] = getattr(ee, "use_raytracing", None)',
    '    info["before"]["samples"] = getattr(ee, "taa_render_samples", None)',
    '    try:',
    '        sc.render.engine = "BLENDER_EEVEE"',
    '        if ee is not None:',
    '            if hasattr(ee, "use_raytracing"):',
    '                ee.use_raytracing = True',
    '            if hasattr(ee, "ray_tracing_method"):',
    '                try:',
    '                    ee.ray_tracing_method = "SCREEN"',
    '                except Exception:',
    '                    pass',
    '            if hasattr(ee, "use_shadows"):',
    '                ee.use_shadows = True',
    '            for attr, val in (("shadow_ray_count", 2), ("shadow_step_count", 8)):',
    '                if hasattr(ee, attr):',
    '                    try:',
    '                        setattr(ee, attr, val)',
    '                    except Exception:',
    '                        pass',
    '            cur = getattr(ee, "taa_render_samples", 64) or 64',
    '            if hasattr(ee, "taa_render_samples") and cur < 64:',
    '                ee.taa_render_samples = 64',
    '        info["configured"] = "eevee-rt" if (ee is not None and getattr(ee, "use_raytracing", False)) else "eevee"',
    '    except Exception as e:',
    '        info["ok"] = False',
    '        info["error"] = "%s: %s" % (type(e).__name__, str(e)[:120])',
    '    info["after"] = {"engine": sc.render.engine, "rt": getattr(ee, "use_raytracing", None),',
    '                     "ray_method": str(getattr(ee, "ray_tracing_method", "")), "samples": getattr(ee, "taa_render_samples", None)}',
    '    info["fell_back_to_cpu"] = False',
    '    info.setdefault("ok", True)',
    '    print("DSH_GPU " + json.dumps(info, ensure_ascii=False))',
    '_dsh_engine_setup()',
    'del _dsh_engine_setup',
].join('\n');
/** Custom-view still (overwritten by default) */
export const VIEW_PNG_WIN = PATHS.viewPngWin;
export const VIEW_PNG_WSL = PATHS.viewPngWsl;
/** Headless Blender executable (WSL-side path; spawn goes through binfmt to start a Windows process); when it is missing the tool gives configuration guidance */
export const BLENDER_EXE = CFG.blenderExe;
export { PKG_ROOT } from './config.js';
/**
 * Persistent kernel bootstrap: the addon's execute_code always runs in a **fresh namespace** (measured in practice: variables do not survive across calls),
 * but sys.modules is the same process → one resident module K carries the state, giving REPL semantics:
 *   K.x = 41        # this call
 *   print(K.x + 1)  # still readable on the next call
 * It also preloads bpy / math / mathutils, saving the repeated import every time.
 */
const PATH_HELPERS_TEMPLATE = [
    'def _dsh_slashes(p):',
    '# macOS / Linux use forward slashes; only Windows needs the reversal',
    '    if __DSH_NATIVE_POSIX__: return str(p)',
    '    return str(p).replace("/", chr(92))',
    'def _dsh_blend_path(p):',
    '    """relative path → absolute path relative to the current .blend (Windows form)"""',
    '    import os as _os',
    '    s = str(p).strip()',
    '    fp = bpy.data.filepath',
    '    base = _os.path.dirname(_dsh_slashes(fp)) if fp else ""',
    '    if s.startswith("//"): s = s[2:]',
    '    if s.startswith("./"): s = s[2:]',
    '    if not s or s == ".": return base',
    '    if _os.path.isabs(s) or (len(s) > 1 and s[1] == ":"): return _dsh_slashes(s)',
    '    return _dsh_slashes(_os.path.join(base, s)) if base else s',
    'def _dsh_win_path(p):',
    '    """any path → a form the Blender process side can use (/mnt/d/x → D:/x; inside WSL → UNC; macOS/Linux native → as is)"""',
    '    if __DSH_NATIVE_POSIX__: return _dsh_blend_path(p)',
    '    s = str(p).strip(); b = chr(92)',
    '    if len(s) > 1 and s[1] == ":": return _dsh_slashes(s)',
    '    if s.startswith("/mnt/") and len(s) > 6: return s[5].upper() + ":" + b + s[7:].replace("/", b)',
    '    if s.startswith(b + b + "wsl"): return _dsh_slashes(s)',
    '    # v0.8.4: a forward-slash UNC (//wsl.localhost/…) is read as "relative to the .blend" inside Blender and fails → normalise it',
    '    if s.startswith("//wsl") or s.startswith("//WSL"): return b + _dsh_slashes(s[1:])',
    '    if s.startswith("//") or s.startswith("./") or (s and not s.startswith("/")): return _dsh_blend_path(s)',
    '    if s.startswith("/"): return b + b + "wsl.localhost" + b + __DISTRO__ + s.replace("/", b)',
    '    return s',
    'def _dsh_wsl_path(p):',
    '    """Windows / UNC path → a form the WSL side can use (D:/x → /mnt/d/x; UNC → /...); native POSIX is returned as is"""',
    '    if __DSH_NATIVE_POSIX__: return _dsh_blend_path(p)',
    '    s = str(p).strip(); b = chr(92)',
    '    if len(s) > 1 and s[1] == ":": return "/mnt/" + s[0].lower() + "/" + s[2:].replace(b, "/").lstrip("/")',
    '    if s.startswith(b + b + "wsl.localhost" + b):',
    '        parts = s.split(b, 4)',
    '        return "/" + (parts[4].replace(b, "/") if len(parts) > 4 else "")',
    '    if s.startswith("/mnt/"): return s',
    '    if s.startswith("//") or s.startswith("./") or (s and not s.startswith("/")): return _dsh_win_path(s)',
    '    return s',
    'def _dsh_run(path, reload_modules=True):',
    '    """run a .py file (WSL / Windows / relative-to-.blend paths all accepted); optionally reload modules from the same directory"""',
    '    import os as _os',
    '    p = _dsh_win_path(path)',
    '    if not _os.path.isfile(p):',
    '        alt = _dsh_wsl_path(p)',
    '        if _os.path.isfile(alt): p = alt',
    '        else: raise FileNotFoundError("script not found: %s (also tried %s)" % (path, alt))',
    '    if reload_modules:',
    '        import importlib as _il, sys as _sy',
    '        d = _os.path.dirname(_os.path.abspath(p))',
    '        _il.invalidate_caches()',
    '        if d not in _sy.path: _sy.path.insert(0, d)',
    '        for _n, _m in list(_sy.modules.items()):',
    '            _f = getattr(_m, "__file__", None)',
    '            if _f and _os.path.dirname(_os.path.abspath(_f)) == d:',
    '                try: _il.reload(_m)',
    '                except Exception: pass',
    '    _g = globals(); _g["__file__"] = p',
    '    with open(p, encoding="utf-8") as _fh: _src = _fh.read()',
    '    exec(compile(_src, p, "exec"), _g)',
    '    return p',
    'def _dsh_stage(path, sub="stage"):',
    '    """copy a file to a local path Blender can definitely read (fallback for UNC / CJK paths). Returns {ok, src, staged, bytes, reason}."""',
    '    import os as _os, shutil as _sh',
    '    src = _dsh_win_path(path)',
    '    info = {"src": src, "staged": src}',
    '    if not _os.path.isfile(src):',
    '        info["ok"] = False; info["reason"] = "source file does not exist"; return info',
    '    try:',
    '        if src.startswith(chr(92) * 2):',
    '            base = str(getattr(K, "out_dir", "") or "")',
    '            d = _os.path.join(base, str(sub))',
    '            _os.makedirs(d, exist_ok=True)',
    '            dst = _os.path.join(d, _os.path.basename(src))',
    '            _sh.copyfile(src, dst)',
    '            info["staged"] = dst; info["bytes"] = _os.path.getsize(dst); info["was_unc"] = True',
    '    except Exception as _e:',
    '        info["ok"] = False; info["reason"] = str(_e)[:120]; return info',
    '    info["ok"] = True; return info',
    'def _dsh_reload_modules(prefixes=None, root=None):',
    '    """hot reload: drop user modules under the given prefixes/directory (a plain import in a hot session hits the old sys.modules code)."""',
    '    import sys as _sys, importlib as _il, os as _os',
    '    _il.invalidate_caches()',
    '    pre = [str(p) for p in (prefixes or []) if str(p)]',
    '    root_abs = _os.path.abspath(root) if root else None',
    '    purged = []',
    '    for _n, _m in list(_sys.modules.items()):',
    '        _f = getattr(_m, "__file__", None)',
    '        _hit = bool(pre) and any(_n == p or _n.startswith(p + ".") for p in pre)',
    '        if not _hit and root_abs and _f:',
    '            try:',
    '                _hit = _os.path.abspath(_f).startswith(root_abs)',
    '            except Exception:',
    '                _hit = False',
    '        if _hit and not _n.startswith("bpy"):',
    '            _sys.modules.pop(_n, None); purged.append(_n)',
    '    return {"purged": purged, "count": len(purged), "prefixes": pre, "root": root_abs}',
    'def _dsh_stage_emit(name, **extra):',
    '    """v0.9.3: stage heartbeat — print("DSH_STAGE {single-line JSON}") with flush=True.',
    '    The plugin side reads the last one from blender_rt_job(op="status").stage / the stdout log.',
    '    Usage: dsh_stage("building") / K.progress("render", i=3, total=12)."""',
    '    import json as _stj, time as _stt, os as _sto',
    '    _d = {"name": str(name), "t": round(_stt.time(), 3), "run": _sto.environ.get("DSH_RUN_ID")}',
    '    _d.update({str(k): v for k, v in extra.items()})',
    '    print("DSH_STAGE " + _stj.dumps(_d, ensure_ascii=False), flush=True)',
    'dsh_stage = _dsh_stage_emit',
    'K.dsh_distro = __DISTRO__',
    'K.win_path = _dsh_win_path',
    'K.wsl_path = _dsh_wsl_path',
    'K.blend_path = _dsh_blend_path',
    'K.run = _dsh_run',
    'K.stage = _dsh_stage',
    'K.progress = _dsh_stage_emit',
    'K.reload_modules = _dsh_reload_modules',
    'K.out_dir = __OUTDIR__',
    '# v0.8.8: the runtime directory is injected too (qc.py uses it to load sibling modules on the spot, e.g. qc_render.py)',
    'K.runtime_dir = __RUNTIME_DIR__',
    'K.workdir = K.out_dir',
    // v0.9.1 (93-B4): parameter/environment contract — inside the subprocess K.args / K.env / K.run_id are directly readable,
    // no need to squeeze parameters into argv or pass them through globals any more (headless injects DSH_ARGS/DSH_OUTDIR/DSH_RUN_ID/DSH_SESSION).
    'try:',
    '    import os as _os_env, json as _json_env',
    '    K.env = _os_env.environ',
    '    K.run_id = _os_env.environ.get("DSH_RUN_ID")',
    '    K.session = _os_env.environ.get("DSH_SESSION")',
    '    K.outdir_env = _os_env.environ.get("DSH_OUTDIR")',
    '    K.args = _json_env.loads(_os_env.environ.get("DSH_ARGS") or "[]")',
    'except Exception:',
    '    K.env = {}; K.args = []; K.run_id = None; K.session = None; K.outdir_env = None',
    '# v0.8.7: path constants are injected into the script namespace too (the standalone-module + exec(open()) style works as well)',
    'DSH_OUT = K.out_dir',
    'DSH_WIN = _dsh_win_path',
    'DSH_WSL = _dsh_wsl_path',
].join('\n');
export const PATH_HELPERS = PATH_HELPERS_TEMPLATE
    // Neither macOS nor "native POSIX that is not WSL" needs cross-OS path rewriting (Blender and the host are on the same machine).
    // The WSL test reuses the project's existing /mnt/c probe and does not depend on WSL_DISTRO_NAME, which may not be exported.
    .replace(/__DSH_NATIVE_POSIX__/g, IS_MAC || (!IS_WIN && !fs.existsSync('/mnt/c')) ? 'True' : 'False')
    .replace(/__DISTRO__/g, JSON.stringify(process.env.WSL_DISTRO_NAME || 'Ubuntu'))
    .replace(/__OUTDIR__/g, JSON.stringify(WIN_TMP))
    .replace(/__RUNTIME_DIR__/g, JSON.stringify(HERE));
/** act wrapper: exceptions also return partial stdout/stderr/traceback (v0.7.0) */
export const ACT_WRAPPER = (src) => [
    'import io as _dsh_io, contextlib as _dsh_ctx, traceback as _dsh_tb, json as _dsh_json',
    '_dsh_src = _dsh_json.loads(' + JSON.stringify(JSON.stringify(src)) + ')',
    '_dsh_o = _dsh_io.StringIO(); _dsh_e = _dsh_io.StringIO()',
    'def _dsh_epoch():',
    '    import bpy as _b',
    '    try:',
    '        h = 0',
    '        for _o in _b.data.objects:',
    '            for _c in _o.name:',
    '                h = (h * 131 + ord(_c)) & 4294967295',
    '            if _o.type == "MESH" and getattr(_o, "data", None) is not None:',
    '                h = (h * 131 + len(_o.data.vertices)) & 4294967295',
    '        return {"objects": len(_b.data.objects), "meshes": len(_b.data.meshes),',
    '                "materials": len(_b.data.materials), "nameHash": h}',
    '    except Exception as _e:',
    '        return {"error": str(_e)[:60]}',
    'def _dsh_epoch_json():',
    '    import json as _j',
    '    return _j.dumps(_dsh_epoch(), ensure_ascii=False)',
    'try:',
    '    with _dsh_ctx.redirect_stdout(_dsh_o), _dsh_ctx.redirect_stderr(_dsh_e):',
    '        exec(compile(_dsh_src, "<rt_do>", "exec"), globals())',
    'except BaseException as _dsh_exc:',
    '    print("DSH_ACT_ERR " + _dsh_json.dumps({"error": "%s: %s" % (type(_dsh_exc).__name__, _dsh_exc), "traceback": _dsh_tb.format_exc()[-6000:], "stdout": _dsh_o.getvalue()[-16000:], "stderr": _dsh_e.getvalue()[-8000:], "epoch": _dsh_epoch()}, ensure_ascii=False))',
    'else:',
    '    print("DSH_ACT_OK " + _dsh_json.dumps({"stdout": _dsh_o.getvalue()[-16000:], "stderr": _dsh_e.getvalue()[-8000:], "epoch": _dsh_epoch()}, ensure_ascii=False))',
].join('\n');
// The kit's **content fingerprint**: folded into every module's invalidation criterion ⇒ touching kit makes all modules re-inject on the next call
export const KIT_SRC = (() => {
    try {
        return fs.readFileSync(KIT_PATH, 'utf8');
    }
    catch (e) {
        return '';
    }
})();
export const KIT_HASH = createHash('sha256').update(KIT_SRC).digest('hex').slice(0, 12);
export const GEO_SRC = (() => {
    try {
        return fs.readFileSync(GEO_PATH, 'utf8');
    }
    catch (e) {
        return '';
    }
})();
export const GEO_HASH = createHash('sha256').update(GEO_SRC).digest('hex').slice(0, 12);
//# sourceMappingURL=paths.js.map