// Job script prelude/body assembly (split out of jobs/script.ts)
import fs from 'node:fs';
import { GPU_PRELUDE, pyModuleFile, pyModuleNames } from '../../../paths.js';
import { slipFixPath } from '../../../core/output/index.js';
import { PATH_GUARD, envPrelude, scriptFileBlock, shotsBlock, workdirBlock, } from '../../../core/scripts.js';
import { KERNEL_BOOTSTRAP } from '../../../core/kernel/index.js';
import { hardExitJobParts } from '../../../hard_exit.js';
import { writeHeadlessScript } from '../../../staging.js';
export function buildJobParts(E, opts, a) {
    const parts = [envPrelude(a.envPairs)];
    if (opts.bootstrap !== false)
        parts.push(KERNEL_BOOTSTRAP);
    parts.push('_dsh_stage_emit("engine-prelude")');
    parts.push([
        'try:',
        '    _DSH_FP0 = bpy.context.scene.render.filepath',
        'except Exception:',
        '    _DSH_FP0 = None',
    ].join(String.fromCharCode(10)));
    if (a.engineMode !== 'keep')
        parts.push(GPU_PRELUDE.replace(/__DSH_ENGINE__/g, "'" + (a.engineMode === 'cycles' ? 'cycles' : 'eevee') + "'").replace(/__DSH_GPU_MANUAL__/g, 'False'));
    // v0.8.9: the job layer supports preload too (same scheme as headless: splice the source of runtime/py/<domain>/<name>.py to the top of the script)
    const jobMods = Array.isArray(opts.preload)
        ? opts.preload
        : opts.preload
            ? String(opts.preload).split(',')
            : [];
    // v0.9.3: the job layer supports shots as well (with as_job=true headless ends up running here)
    const jobShotsSpec = Array.isArray(opts.shots)
        ? { views: opts.shots }
        : opts.shots && typeof opts.shots === 'object'
            ? Object.assign({}, opts.shots)
            : null;
    const jobShotsWanted = !!(jobShotsSpec &&
        Array.isArray(jobShotsSpec.views) &&
        jobShotsSpec.views.length);
    if (jobShotsWanted && !jobMods.some((m) => String(m).trim().replace(/\.py$/, '') === 'qc_render'))
        jobMods.push('qc_render');
    for (const m of jobMods) {
        const name = String(m).trim().replace(/\.py$/, '');
        if (!name)
            continue;
        // The real module files live under runtime/py/<domain>/ (single manifest runtime/py/modules.json);
        // the injection channel must carry the real implementation file, otherwise the exec'ed chunk is just an import statement.
        let f;
        try {
            f = pyModuleFile(name);
        }
        catch (e2) {
            f = null;
        }
        if (!f || !fs.existsSync(f)) {
            // On error hand out the available module names directly — otherwise "wanting preload=vehicle" in the field is pure trial and error.
            throw new Error('preload module not found: ' +
                name +
                ' (available module names: ' +
                pyModuleNames().join(', ') +
                ') — preload takes a module name (runtime/py/<domain>/<name>.py, manifest runtime/py/modules.json), e.g. preload="vehicle,audit"; for offline use (backend down) see runtime/py/core/offline_bootstrap.py');
        }
        parts.push(E.preloadChunk(name));
    }
    parts.push('_dsh_stage_emit("preload-done")');
    if (opts.workdir)
        parts.push(workdirBlock(slipFixPath(String(opts.workdir), null)));
    if (a.scriptFileInfo)
        parts.push(scriptFileBlock(a.scriptFileInfo.resolved));
    parts.push(a.script);
    parts.push('_dsh_stage_emit("script-end")');
    if (jobShotsWanted)
        parts.push(shotsBlock(Object.assign({ engine: 'keep', lock: true, warmup: true, tag: 'shot' }, jobShotsSpec, {
            outdir: a.outdirWin,
        })));
    parts.push(PATH_GUARD);
    parts.push('_dsh_stage_emit("done")');
    // F-14: after done, flush stdout/stderr then os._exit(0) (skips Blender's exit teardown; hardExit=false restores the old behaviour)
    for (const hx of hardExitJobParts(opts))
        parts.push(hx);
    const sp = writeHeadlessScript(parts.join('\n'));
    const timeoutMs = Math.max(1000, Math.min(86400000, Number(opts.timeoutMs) || 3600000));
    return { parts, jobShotsSpec, sp, timeoutMs };
}
/** Script written to disk + Blender argument finalisation */
export function finalizeJobArgs(a, built, opts) {
    a.args.push('--python', built.sp.win, '--');
    if (opts.outdir)
        a.args.push(a.outdirWin);
    if (Array.isArray(opts.args))
        for (const v of opts.args)
            a.args.push(String(v));
}
//# sourceMappingURL=preload.js.map