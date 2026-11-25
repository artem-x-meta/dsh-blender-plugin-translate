// headless options: preload and the GPU/engine prelude (split out of options.ts)
import fs from 'node:fs';
import { GPU_PRELUDE, pyModuleFile } from '../../../paths.js';
export function buildHeadlessPreload(opts, deps) {
    // preload: splice the source of runtime python modules (view/perf/runner/contract/planner...) into the top of the script
    const mods = Array.isArray(opts.preload)
        ? opts.preload
        : opts.preload
            ? String(opts.preload).split(',')
            : [];
    // ---- v0.9.3: shots=[…] multi-view rendering in one go — qc_render is pulled in automatically (the render harness lives there)
    const shotsSpec = Array.isArray(opts.shots)
        ? { views: opts.shots }
        : opts.shots && typeof opts.shots === 'object'
            ? Object.assign({}, opts.shots)
            : null;
    const shotsWanted = !!(shotsSpec && Array.isArray(shotsSpec.views) && shotsSpec.views.length);
    if (shotsWanted && !mods.some((m) => String(m).trim().replace(/\.py$/, '') === 'qc_render'))
        mods.push('qc_render');
    let pre = '';
    for (const m of mods) {
        const name = String(m).trim().replace(/\.py$/, '');
        if (!name)
            continue;
        // same as the job layer: take the real file under runtime/py/<domain>/ (the old path is a shim).
        const f = pyModuleFile(name);
        if (!fs.existsSync(f))
            throw new Error('preload cannot find module: ' + name + ' (' + f + ')');
        pre += deps.preloadChunk(name) + '\n';
    }
    return { mods, pre, shotsSpec, shotsWanted };
}
export function buildEnginePrelude(opts) {
    // ---- engine prelude (v0.8.0): eevee + raytracing by default; cycles / keep optional (gpu:"false"=keep for backward compatibility)
    const engineMode = String(opts.engine === undefined || opts.engine === null ? 'eevee' : opts.engine).toLowerCase();
    const legacyGpu = String(opts.gpu === undefined || opts.gpu === null ? '' : opts.gpu).toLowerCase();
    const gpuOff = engineMode === 'keep' ||
        engineMode === 'off' ||
        engineMode === 'none' ||
        legacyGpu === 'false' ||
        legacyGpu === 'off' ||
        legacyGpu === '0';
    const gpuManual = legacyGpu === 'true' || legacyGpu === 'required';
    let gpuPre = '';
    if (!gpuOff) {
        const modeLit = engineMode === 'cycles' || engineMode === 'cycle' ? 'cycles' : 'eevee';
        gpuPre =
            '# ---- DSH engine prelude (' +
                modeLit +
                ') ----\n' +
                GPU_PRELUDE.replace(/__DSH_ENGINE__/g, "'" + modeLit + "'").replace(/__DSH_GPU_MANUAL__/g, gpuManual ? 'True' : 'False') +
                '\n';
    }
    return { engineMode, gpuOff, gpuManual, gpuPre };
}
//# sourceMappingURL=gpu.js.map