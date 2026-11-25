// Launch resolution: Windows agent / addon name hints / injected script (split out of launch.ts)
import { CFG } from '../config.js';
import { errorMessage } from '../core/json.js';
export async function tryLaunchAgent(opts, addonPort, steps, base) {
    const url = String(CFG.launchAgentUrl || '');
    if (!url || url.toLowerCase() === 'off')
        return null;
    if (opts.interop === true)
        return null;
    try {
        const ac = new AbortController();
        const t = setTimeout(() => ac.abort(), 1500);
        const h = await fetch(url + '/health', { signal: ac.signal });
        clearTimeout(t);
        if (!h.ok)
            return null;
    }
    catch (e) {
        return null;
    }
    steps.push('Windows launch agent online: ' + url + ' (zero interop calls this launch)');
    const ac = new AbortController();
    const t = setTimeout(() => ac.abort(), 15000);
    try {
        const r = await fetch(url + '/launch', {
            method: 'POST',
            headers: { 'content-type': 'application/json' },
            body: JSON.stringify({
                addonPort: addonPort,
                file: opts.file ? String(opts.file) : null,
                force: !!opts.force,
                blenderExe: opts.exe ? String(opts.exe) : null,
            }),
            signal: ac.signal,
        });
        const j = (await r.json());
        steps.push('agent accepted: already=' + String(!!j.already) + ' dispatched=' + String(!!j.dispatched));
        return Object.assign({}, base, j, { via: 'windows-agent' });
    }
    catch (e) {
        steps.push('agent call unconfirmed (' + errorMessage(e) + ') —— treated as dispatched, no interop fallback so it is not launched twice');
        return Object.assign({}, base, {
            ok: false,
            already: false,
            dispatched: true,
            launched: true,
            listening: false,
            addonPort: addonPort,
            via: 'windows-agent',
        });
    }
    finally {
        clearTimeout(t);
    }
}
/**
 * **Name hints** for addon autodetection: only this repo's `DSH Blender Bridge` is recognized (module `dsh_blender_bridge`, prefix `dshbb_*`).
 * Since v2.3 the old `MCP for Blender` (module `blender_mcp`) is no longer scanned or supported.
 * LAUNCH_BOOT_PY inlines them via JSON.stringify into **the same** list; `addonNameHit()` is its JS mirror with the same convention (for tests).
 */
export const ADDON_NAME_HINTS = ['blender_bridge', 'dshbb', 'dsh_blender_bridge'];
/** JS predicate using the same convention as `_name_hit()` in LAUNCH_BOOT_PY (lowercased substring hit) —— for tests */
export function addonNameHit(name) {
    const n = String(name || '').toLowerCase();
    return ADDON_NAME_HINTS.some((k) => n.includes(k));
}
/** Bootstrap script source injected into Blender (exported so self-checks can assert "the Python that lands on disk really hits both names") */
export const LAUNCH_BOOT_PY = [
    '"""DSH launch boot (v0.9.4): enable the Blender addon and start its socket server (GUI only)."""',
    'import importlib.util, json, os, sys',
    '',
    '# ---- DSH addon name hints: only dsh_blender_bridge / dshbb_* are recognized (the old MCP for Blender is no longer supported) ----',
    '_HINTS = ' + JSON.stringify(ADDON_NAME_HINTS),
    'def _name_hit(name):',
    '    n = (name or "").lower()',
    '    return any(k in n for k in _HINTS)',
    '# ---- /DSH addon name hints ----',
    '',
    '_res = {',
    '    "ok": False, "background": None, "enabled": [], "loaded_by": None, "server_running": False,',
    '    "addon_file": None, "errors": [], "addon_modules_seen": [],',
    '    "addon_version": None, "addon_protocol": None, "addon_ok": False,',
    '    "env": {"BLENDER_USER_SCRIPTS": os.environ.get("BLENDER_USER_SCRIPTS", ""),',
    '            "DSH_BLENDER_ADDON_FILE": os.environ.get("DSH_BLENDER_ADDON_FILE", ""),',
    '            "DSH_BLENDER_ADDON_MODULE": os.environ.get("DSH_BLENDER_ADDON_MODULE", "")},',
    '}',
    '',
    '',
    'def _flush():',
    '    p = os.environ.get("DSH_BLENDER_LAUNCH_STATUS", "")',
    '    if not p:',
    '        return',
    '    try:',
    '        d = os.path.dirname(p)',
    '        if d and not os.path.isdir(d):',
    '            os.makedirs(d, exist_ok=True)',
    '        with open(p, "w", encoding="utf-8") as fh:',
    '            json.dump(_res, fh, ensure_ascii=False, indent=1)',
    '    except Exception as exc:',
    '        _res["status_write_error"] = repr(exc)',
    '',
    '',
    'def _addon_meta():',
    '    mod = sys.modules.get("dsh_blender_bridge")',
    '    if mod is None:',
    '        try:',
    '            mod = importlib.import_module("dsh_blender_bridge")',
    '        except Exception:',
    '            mod = None',
    '    if mod is None:',
    '        _res["errors"].append("addon metadata unavailable: dsh_blender_bridge not importable")',
    '        return',
    '    if not hasattr(mod, "__path__"):',
    '        _res["errors"].append("addon metadata unavailable: dsh_blender_bridge is not a package (single-file installs are unsupported)")',
    '        return',
    '    info = getattr(mod, "bl_info", {}) or {}',
    '    version = info.get("version")',
    '    protocol = getattr(mod, "ADDON_PROTOCOL_VERSION", None)',
    '    _res["addon_version"] = list(version) if version else None',
    '    _res["addon_protocol"] = protocol',
    '    try:',
    '        _res["addon_ok"] = bool(protocol == 11 and version and tuple(version) >= (1, 10))',
    '    except Exception:',
    '        _res["addon_ok"] = False',
    '    if not _res["addon_ok"]:',
    '        _res["errors"].append("addon contract mismatch: version=%r protocol=%r (need >=1.10 / 11)" % (version, protocol))',
    '',
    '',
    'def _report():',
    '    _res["server_running"] = bool(_server_running())',
    '    _addon_meta()',
    '    _res["ok"] = bool(_res["server_running"] and _res["addon_ok"])',
    '    _flush()',
    '    print("DSH_LAUNCH " + json.dumps(_res, ensure_ascii=False), flush=True)',
    '',
    '',
    'def _server_cls():',
    '    return getattr(bpy.types, "dshbb_server", None)',
    '',
    '',
    'def _server_running():',
    '    t = _server_cls()',
    '    try:',
    '        return bool(t and getattr(t, "running", False))',
    '    except Exception:',
    '        return False',
    '',
    '',
    'def main():',
    '    _res["background"] = bool(bpy.app.background)',
    '    if bpy.app.background:',
    '        _res["errors"].append("background mode: the addon explicitly refuses to start the server under -b; use the GUI (without -b)")',
    '        return',
    '    want = [m.strip() for m in (os.environ.get("DSH_BLENDER_ADDON_MODULE", "") or "").split(",") if m.strip()]',
    '    try:',
    '        import addon_utils',
    '        mods = list(addon_utils.modules())',
    '        _res["addon_modules_seen"] = [getattr(m, "__name__", "") for m in mods][:60]',
    '        names = want or [getattr(m, "__name__", "") for m in mods if _name_hit(getattr(m, "__name__", ""))]',
    '        for n in names:',
    '            try:',
    '                addon_utils.enable(n, default_set=True, persistent=True)',
    '                _res["enabled"].append(n)',
    '                if _server_running():',
    '                    _res["loaded_by"] = "addon_utils:" + n',
    '                    return',
    '            except Exception as exc:',
    '                _res["errors"].append("enable %s: %r" % (n, exc))',
    '    except Exception as exc:',
    '        _res["errors"].append("addon_utils: %r" % (exc,))',
    '    # Fallback: import directly by file + register()',
    '    # (after Blender 5.x switched to the extension layout, addon_utils may not find the old scripts/addons/*.py)',
    '    cands = []',
    '    given = os.environ.get("DSH_BLENDER_ADDON_FILE", "")',
    '    if given:',
    '        cands.append(given)',
    '    addons_dir = os.path.join(os.environ.get("BLENDER_USER_SCRIPTS", ""), "addons")',
    '    try:',
    '        for f in sorted(os.listdir(addons_dir)):',
    '            p = os.path.join(addons_dir, f)',
    '            if f.lower().endswith(".py") and _name_hit(f):',
    '                cands.append(p)',
    '            elif os.path.isdir(p) and os.path.isfile(os.path.join(p, "__init__.py")) and _name_hit(f):',
    '                cands.append(p)',
    '            elif f.lower().endswith(".zip") and _name_hit(f):',
    '                cands.append(p)',
    '    except Exception:',
    '        pass',
    '    for p in cands:',
    '        try:',
    '            if os.path.isdir(p):',
    '                name = os.path.basename(p)',
    '                init = os.path.join(p, "__init__.py")',
    '                spec = importlib.util.spec_from_file_location(name, init, submodule_search_locations=[p])',
    '                mod = importlib.util.module_from_spec(spec)',
    '                sys.modules[name] = mod',
    '                spec.loader.exec_module(mod)',
    '            elif p.lower().endswith(".zip"):',
    '                if p not in sys.path:',
    '                    sys.path.insert(0, p)',
    '                mod = importlib.import_module("dsh_blender_bridge")',
    '            else:',
    '                spec = importlib.util.spec_from_file_location("dsh_launch_" + os.path.basename(p)[:-3], p)',
    '                mod = importlib.util.module_from_spec(spec)',
    '                sys.modules[spec.name] = mod',
    '                spec.loader.exec_module(mod)',
    '            if not _server_cls() and hasattr(mod, "register"):',
    '                mod.register()',
    '            _res["addon_file"] = p',
    '            _res["loaded_by"] = "direct-import:" + os.path.basename(p)',
    '            if _server_running():',
    '                return',
    '        except Exception as exc:',
    '            _res["errors"].append("direct import %s: %r" % (p, exc))',
    '',
    '',
    'try:',
    '    import bpy',
    'except Exception as _e:',
    '    _res["errors"].append("no bpy: %r" % (_e,))',
    '    _report()',
    'else:',
    '    main()',
    '    _report()',
].join(String.fromCharCode(10));
//# sourceMappingURL=resolve.js.map