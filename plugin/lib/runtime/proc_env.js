/**
 * Subprocess environment and safe JSON reading (moved out of engine.mjs) — launch.mjs needs them (the dependency was missed when moving).
 */
import fs from 'node:fs';
import { IS_MAC, IS_WIN } from './config.js';
/**
 * v0.9.3 (external feedback 2026-09-24): base subprocess environment — all three spawn sites go through it.
 *
 * Older versions only injected PYTHONIOENCODING. When Blender's Python stdout is redirected (pipe) it is **block-buffered**,
 * so the job's stdout.log / stderr.log stay at **0 bytes for the whole run**, and are only written when the process exits
 * (measured by Lead: both logs stayed at 0 bytes through a 20-minute render; engine: 'in the 399 s run there was no stage information at all, 6 minutes of pure black box').
 * PYTHONUNBUFFERED=1 makes print flush immediately → stage heartbeats and incremental logs only mean something then.
 */
function baseChildEnv(extra) {
    return Object.assign({}, process.env, { PYTHONIOENCODING: 'utf-8', PYTHONUNBUFFERED: '1' }, extra || {});
}
/** WSLENV declaration (v0.9.1 field trap: when the WSL side spawns a Windows process the env does not cross the boundary automatically) — shared by headless and job
 *  On macOS / Windows the parent and child processes share one OS, env is inherited naturally, this step is unnecessary. */
function withWslEnv(childEnv, extraEnv) {
    if (IS_MAC || IS_WIN)
        return childEnv; // same OS, env is inherited directly; WSLENV is meaningless and pollutes the child env
    try {
        const pass = Object.keys(childEnv).filter((k) => k.indexOf('DSH_') === 0 || (extraEnv && Object.prototype.hasOwnProperty.call(extraEnv, k)));
        const spec = pass.map((k) => k + '/w').join(':');
        childEnv.WSLENV = childEnv.WSLENV ? childEnv.WSLENV + ':' + spec : spec;
    }
    catch (e) {
        /* if WSLENV cannot be assembled, skip it — injection inside the script is the main path */
    }
    return childEnv;
}
/** Turn "workDir not shared, script lands elsewhere" into a pathWarning **appended at the end** (same shape as pathAudit: carries a hint).
 *  Why append instead of prepending: the existing pathAudit assertions (e.g. acceptance_v093) look at pathWarnings[0], do not steal its position. */
function workdirStagingWarning(staging) {
    if (!staging || !staging.substituted)
        return null;
    return {
        code: 'WORKDIR_NOT_SHARED',
        value: String(staging.requestedWhy || ''),
        evidence: String(staging.note || ''),
        hint: 'workDir (' +
            staging.requested +
            ') is not guaranteed visible on the Windows side → the headless script would land where blender.exe cannot open it.' +
            'point DSH_BLENDER_WORKDIR / workDir in the config at a Windows-visible directory (D:\\… or the distro root filesystem ~/.dsh/…)',
    };
}
/** Read JSON; a bad file returns null (shared by engine and launch) */
function readJsonSafe(p) {
    try {
        return JSON.parse(fs.readFileSync(p, 'utf8'));
    }
    catch (e) {
        return null;
    }
}
export { baseChildEnv, withWslEnv, readJsonSafe, workdirStagingWarning };
//# sourceMappingURL=proc_env.js.map