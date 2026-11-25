// headless options entry (split): paths / prelude / env / deadlines
import { PLUGIN_VERSION } from '../../../core/evidence.js';
import { resolveHeadlessPaths } from './paths.js';
import { buildEnginePrelude, buildHeadlessPreload } from './gpu.js';
export function prepareHeadlessOptions(opts, deps) {
    const { outdirArg, outdirWsl, outdirWin, scriptFileInfo, fileOpt, fileLooksPython, inputFileInfo, script, } = resolveHeadlessPaths(opts, deps);
    const { mods, pre, shotsSpec, shotsWanted } = buildHeadlessPreload(opts, deps);
    const { engineMode, gpuOff, gpuManual, gpuPre } = buildEnginePrelude(opts);
    // ---- v0.9.3: **runId decided first** (the client may bring its own id) —— when the client's wait window expires it must be able to report at once
    // "go collect with this id", so the id has to exist before the request goes out; it cannot wait for the server to generate one and send it back.
    const runId = /^[A-Za-z0-9_-]{1,64}$/.test(String(opts.runId || ''))
        ? String(opts.runId)
        : 'run-' + Date.now().toString(36) + Math.random().toString(36).slice(2, 5);
    const envPairs = {
        DSH_RUN_ID: runId,
        DSH_OUTDIR: outdirWin,
        DSH_SESSION: deps.SESSION_NAME,
        DSH_PLUGIN_VERSION: PLUGIN_VERSION,
        DSH_ARGS: JSON.stringify(Array.isArray(opts.args) ? opts.args.map(String) : []),
    };
    const envOpt = opts.env && typeof opts.env === 'object' ? opts.env : null;
    if (envOpt)
        for (const k of Object.keys(envOpt))
            envPairs[String(k)] = String(envOpt[k]);
    if (scriptFileInfo)
        envPairs.DSH_SCRIPT_FILE = scriptFileInfo.resolved; // feedback #4
    // v0.8.10: expect sentinels before/after —— "build returns empty but does not raise" must be judged a failure
    const exp = opts.expect && typeof opts.expect === 'object' ? opts.expect : null;
    const timeoutMs = Math.max(1000, Math.min(1800000, Number(opts.timeoutMs) || 180000));
    return {
        opts,
        outdirArg,
        outdirWsl,
        outdirWin,
        scriptFileInfo,
        fileOpt,
        fileLooksPython,
        inputFileInfo,
        script,
        mods,
        shotsSpec,
        shotsWanted,
        engineMode,
        gpuOff,
        gpuManual,
        runId,
        envPairs,
        envOpt,
        exp,
        pre,
        gpuPre,
        timeoutMs,
    };
}
//# sourceMappingURL=index.js.map