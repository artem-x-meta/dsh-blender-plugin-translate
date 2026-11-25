// Python script prelude/epilogue: workdir, script-file context, env, PATH_GUARD, shots, file fingerprint
// @imports
import { IS_MAC, IS_WIN, IS_WSL } from '../config.js';
import fs from 'node:fs';
import { createHash } from 'node:crypto';
import { errorMessage } from './json.js';
function workdirBlock(p) {
    return [
        '# ---- DSH workdir ----',
        'try:',
        '    import os as _os, sys as _sys',
        '    _wd = K.win_path(' + JSON.stringify(String(p)) + ')',
        '    _os.chdir(_wd)',
        '    if _wd not in _sys.path: _sys.path.insert(0, _wd)',
        '    print("DSH_WORKDIR " + _wd)',
        'except Exception as _e:',
        '    print("DSH_WORKDIR_ERR " + str(_e)[:120])',
    ].join('\n');
}
/**
 * v0.9.6 (field feedback #4 · hit by the MK1 smoke test): script_file content is **inlined** into dsh_headless_*.py,
 * so inside the script __file__ points at that temporary wrapper file and the script's own directory is not on sys.path either —— the first
 * import of a multi-file project dies with ModuleNotFoundError: No module named 'spec'. Here we explicitly hand the original path and directory back to the script.
 */
function scriptFileBlock(origWinPath) {
    return [
        '# ---- DSH script-file context (v0.9.6 · feedback #4) ----',
        'try:',
        '    import os as _osf, sys as _sysf',
        '    _sf = K.win_path(' + JSON.stringify(String(origWinPath)) + ')',
        '    __file__ = _sf',
        '    _sfd = _osf.path.dirname(_sf)',
        '    if _sfd and _sfd not in _sysf.path:',
        '        _sysf.path.insert(0, _sfd)',
        '    print("DSH_SCRIPT_FILE " + _sf)',
        'except Exception as _e:',
        '    print("DSH_SCRIPT_FILE_ERR " + str(_e)[:120])',
    ].join('\n');
}
function envPrelude(envPairs) {
    return [
        '# ---- DSH env prelude (visible inside the child process; bypasses WSL interop env filtering) ----',
        'try:',
        '    import os as _os_pre, json as _json_pre, time as _time_pre',
        '    _os_pre.environ.update(' + JSON.stringify(envPairs) + ')',
        '    def _dsh_stage_emit(name, **extra):',
        '        _d = {"name": str(name), "t": round(_time_pre.time(), 3), "run": _os_pre.environ.get("DSH_RUN_ID")}',
        '        _d.update({str(k): v for k, v in extra.items()})',
        '        print("DSH_STAGE " + _json_pre.dumps(_d, ensure_ascii=False), flush=True)',
        'except Exception:',
        '    def _dsh_stage_emit(name, **extra):',
        '        pass',
        'try:',
        '    def _dsh_progress_emit(**fields):',
        '        _dp = {"t": round(_time_pre.time(), 3), "run": _os_pre.environ.get("DSH_RUN_ID")}',
        '        _dp.update({str(k): v for k, v in fields.items()})',
        '        print("DSH_PROGRESS " + _json_pre.dumps(_dp, ensure_ascii=False), flush=True)',
        '        return _dp',
        'except Exception:',
        '    def _dsh_progress_emit(**fields):',
        '        pass',
        'dsh_progress = _dsh_progress_emit',
        'dsh_stage = _dsh_stage_emit',
        '_dsh_stage_emit("boot")',
    ].join('\n');
}
/**
 * v0.9.3: path health check —— Windows Blender treats '/home/x' as "a relative path under the root of the current drive"
 * and silently writes to C:\home\x (evidence: Saved: 'C:homesixtyseven67DSH…' immediately followed by os.path.exists() -> false).
 * Here we check scene.render.filepath at the end of the script; together with scanning for Saved: in stdout (pathAudit).
 *
 * The precondition for this check is "WSL host + Windows build of Blender": only that combination misreads POSIX absolute paths.
 * On native Linux Blender and the host are the same machine and OS, so '/home/x' is simply correct ⇒ it must be switched off, otherwise every normal script
 * returns a bogus `render_filepath_posix` warning and pushes people in the wrong direction of "change it to the Windows form" (issue #11).
 */
export const PATH_GUARD = IS_MAC || IS_WIN || !IS_WSL
    ? ''
    : [
        '# ---- DSH path health check (v0.9.3) ----',
        'try:',
        '    import json as _dsh_pj',
        '    _dsh_pw = []',
        '    _dsh_fp = bpy.context.scene.render.filepath',
        '    _dsh_fp0 = globals().get("_DSH_FP0")',
        '    if isinstance(_dsh_fp, str) and _dsh_fp.startswith("/") and not _dsh_fp.startswith("//") and _dsh_fp != _dsh_fp0:',
        '        _dsh_pw.append({"code": "render_filepath_posix", "value": _dsh_fp[:200],',
        '                        "hint": "scene.render.filepath is a POSIX absolute path; Windows Blender will write it to C:\\\\home\\\\… —— use K.win_path(p) to convert it to the Windows form"})',
        '    if _dsh_pw:',
        '        print("DSH_PATH_WARN " + _dsh_pj.dumps({"warnings": _dsh_pw}, ensure_ascii=False), flush=True)',
        'except Exception:',
        '    pass',
    ].join('\n');
function shotsBlock(args) {
    // ⚠ What JSON.stringify produces is a JS literal (true/false/null), **not a Python literal** —— inlining it directly raises NameError: true.
    // So go through json.loads(<JSON string literal>): safe and it keeps the true/false/null semantics.
    return [
        '# ---- DSH shots (v0.9.3): multi-view rendering in one pass ----',
        'import json as _dsh_sjson, bpy as _dsh_sbpy',
        '_dsh_shots_args = _dsh_sjson.loads(' + JSON.stringify(JSON.stringify(args)) + ')',
        'try:',
        '    _dsh_sc = _dsh_sbpy.context.scene',
        '    _dsh_shots_args.setdefault("res", [int(_dsh_sc.render.resolution_x), int(_dsh_sc.render.resolution_y)])',
        '    _dsh_shots_args.setdefault("samples", int(getattr(getattr(_dsh_sc, "eevee", None), "taa_render_samples", 0)',
        '                                              or getattr(getattr(_dsh_sc, "cycles", None), "samples", 0) or 64))',
        '    _dsh_sr = qc_render_views(_dsh_shots_args)',
        '    _dsh_shots_res = _dsh_sjson.loads(_dsh_sr) if isinstance(_dsh_sr, str) else _dsh_sr',
        'except Exception as _dsh_se:',
        '    import traceback as _dsh_stb',
        '    _dsh_shots_res = {"ok": False, "error": "%s: %s" % (type(_dsh_se).__name__, _dsh_se), "traceback": _dsh_stb.format_exc()[-2000:]}',
        'print("DSH_SHOTS " + _dsh_sjson.dumps(_dsh_shots_res, ensure_ascii=False), flush=True)',
    ].join('\n');
}
/** File fingerprint: returns {path,size,mtimeMs,md5,md5Partial}; >512MB hashes only the first 64MB and flags it as partial */
function fileFingerprint(winPath, wslPath) {
    const out = {
        path: winPath ? String(winPath) : null,
        wsl: wslPath ? String(wslPath) : null,
    };
    try {
        const st = fs.statSync(wslPath);
        out.size = st.size;
        out.mtimeMs = st.mtimeMs;
        out.mtime = new Date(st.mtimeMs).toISOString();
        const LIMIT = 64 * 1024 * 1024;
        if (st.size > 512 * 1024 * 1024) {
            out.md5 = md5File(wslPath, LIMIT);
            out.md5Partial = true;
            out.md5Note = 'file >512MB: only the first 64MB is hashed (enough to detect changes together with size/mtime)';
        }
        else
            out.md5 = md5File(wslPath);
    }
    catch (e) {
        out.error = errorMessage(e).slice(0, 160);
    }
    return out;
}
function md5File(p, limit) {
    const h = createHash('md5');
    const fd = fs.openSync(p, 'r');
    try {
        const buf = Buffer.alloc(1 << 20);
        let total = 0;
        for (;;) {
            const n = fs.readSync(fd, buf, 0, buf.length, null);
            if (!n)
                break;
            if (limit && total + n > limit) {
                h.update(buf.subarray(0, Math.max(0, limit - total)));
                break;
            }
            h.update(buf.subarray(0, n));
            total += n;
        }
    }
    finally {
        try {
            fs.closeSync(fd);
        }
        catch (e) {
            /* ignore */
        }
    }
    return h.digest('hex');
}
export { workdirBlock, scriptFileBlock, envPrelude, shotsBlock, fileFingerprint, md5File };
//# sourceMappingURL=scripts.js.map