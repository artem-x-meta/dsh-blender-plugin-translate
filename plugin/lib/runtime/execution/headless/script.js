import { PATH_GUARD, envPrelude, scriptFileBlock, shotsBlock, workdirBlock, } from '../../core/scripts.js';
import { KERNEL_BOOTSTRAP } from '../../core/kernel/index.js';
import { hardExitSyncTail } from '../../hard_exit.js';
import { writeHeadlessScript } from '../../staging.js';
import { slipFixPath } from '../../core/output/index.js';
import { wslToWin } from '../../config.js';
/**
 * Assemble the Python prelude/body and Blender argv. Pure string construction except for
 * the temporary script file written by writeHeadlessScript (which is the staging seam).
 */
export function buildHeadlessScript(p) {
    const opts = p.opts;
    const headParts = [];
    // ---- v0.9.1 (93-B4): env injection must happen before the K kernel — K.args/K.run_id in PATH_HELPERS are read from os.environ,
    // and env does not cross WSL→Windows reliably (measured: DSH_* gets eaten) → just setdefault them once inside the script.
    headParts.push(envPrelude(p.envPairs));
    if (opts.bootstrap !== false)
        headParts.push(KERNEL_BOOTSTRAP);
    headParts.push('_dsh_stage_emit("engine-prelude")');
    // Baseline: record render.filepath before entering the script (the --factory-startup default is itself a '/tmp\\' style
    // POSIX string) — only **the script turning it into a POSIX absolute path** is worth warning about, anything else is a false positive.
    headParts.push([
        'try:',
        '    _DSH_FP0 = bpy.context.scene.render.filepath',
        'except Exception:',
        '    _DSH_FP0 = None',
    ].join(String.fromCharCode(10)));
    if (p.gpuPre)
        headParts.push(p.gpuPre);
    // v0.8.10: workdir → chdir inside the script + first sys.path entry (Blender is a Windows process, so it has to go through K.win_path)
    if (opts.workdir)
        headParts.push(workdirBlock(slipFixPath(String(opts.workdir), null)));
    if (p.scriptFileInfo)
        headParts.push(scriptFileBlock(p.scriptFileInfo.resolved));
    const expectPre = p.exp
        ? [
            '# ---- DSH expect: before ----',
            'import json as _dsh_ejson',
            '_DSH_EXP0 = {"objects": len(bpy.data.objects), "meshes": len(bpy.data.meshes), "materials": len(bpy.data.materials)}',
        ].join(String.fromCharCode(10))
        : '';
    const expectPost = p.exp
        ? [
            '# ---- DSH expect: after ----',
            'try:',
            '    _DSH_EXP1 = {"objects": len(bpy.data.objects), "meshes": len(bpy.data.meshes), "materials": len(bpy.data.materials)}',
            '    print("DSH_EXPECT " + _dsh_ejson.dumps({"before": _DSH_EXP0, "after": _DSH_EXP1, "delta": {k: _DSH_EXP1[k] - _DSH_EXP0[k] for k in _DSH_EXP1}}))',
            'except Exception as _e:',
            '    print("DSH_EXPECT " + _dsh_ejson.dumps({"error": str(_e)[:160]}))',
        ].join(String.fromCharCode(10))
        : '';
    const NL = String.fromCharCode(10);
    // v0.9.3: shots go through qc_render_views — outdir takes the Windows form (Blender side), the remaining keys are up to the caller
    const shotsPre = p.shotsWanted
        ? shotsBlock(Object.assign({ engine: 'keep', lock: true, warmup: true, tag: 'shot' }, p.shotsSpec, {
            outdir: p.outdirWin,
        })) + NL
        : '';
    let body = p.script || p.pre || p.gpuPre || shotsPre
        ? (headParts.length ? headParts.join(NL) + NL : '') +
            (expectPre ? expectPre + NL : '') +
            p.pre +
            '_dsh_stage_emit("preload-done")' +
            NL +
            p.script +
            NL +
            '_dsh_stage_emit("script-end")' +
            NL +
            shotsPre +
            PATH_GUARD +
            NL +
            (expectPost ? expectPost : '') +
            NL +
            '_dsh_stage_emit("done")' +
            NL
        : '';
    // F-14: after done, flush stdout/stderr then os._exit(0) (skips Blender teardown; hardExit=false restores the old behaviour).
    // An empty body appends nothing (same guard as `if (body)` at 2745): a run without a script should not gain a phantom --python that only carries the exit line.
    if (body)
        body += hardExitSyncTail(opts, NL);
    const args = ['-b'];
    if (p.fileOpt && !p.fileLooksPython)
        args.push(wslToWin(String(p.fileOpt)));
    if (opts.factoryStartup !== false)
        args.push('--factory-startup');
    let sp = null;
    if (body) {
        sp = writeHeadlessScript(body);
        args.push('--python', sp.win);
    }
    args.push('--');
    if (opts.outdir)
        args.push(p.outdirWin);
    if (Array.isArray(opts.args))
        args.push(...opts.args.map(String));
    return { body, args, sp };
}
//# sourceMappingURL=script.js.map