// Shared blender.exe pre-flight check (first-call job channel):
// both the worker and the job spawn paths must fail before spawn, otherwise Node throws a TypeError synchronously and
// child.on('error') / the hint in the readiness check is never reached.
import { CFG } from '../config.js';
/**
 * Throw a structured blender_exe_missing when blenderExe is empty/blank (code + actionable config hint).
 * retryTool is used for the retry action at the end of the hint (differs between worker and job).
 */
export function assertBlenderExe(exe, detectedFrom, retryTool = 'blender_rt_worker op=start') {
    if (typeof exe === 'string' && exe.trim())
        return;
    const from = detectedFrom === undefined || detectedFrom === null || !String(detectedFrom).trim()
        ? blenderExeSource()
        : String(detectedFrom);
    const err = new Error('Blender executable not found (blenderExe is empty; detection source: ' + from + ')');
    err.code = 'blender_exe_missing';
    err.hint =
        'Set DSH_BLENDER_EXE or blenderExe in dsh-blender.config.json (current detection source: ' +
            from +
            '); a Steam build path looks like <Steam>\\steamapps\\common\\Blender\\blender.exe (e.g. D:\\Program Files\\Steam\\steamapps\\common\\Blender\\blender.exe); after changing it, restart DSH and then run ' +
            retryTool;
    throw err;
}
export function blenderExeSource() {
    try {
        const cfg = CFG;
        const from = cfg.source ? cfg.source.blenderExe : undefined;
        if (from !== undefined && from !== null && String(from).trim())
            return String(from);
    }
    catch (e) { }
    return 'unknown';
}
//# sourceMappingURL=exe-guard.js.map