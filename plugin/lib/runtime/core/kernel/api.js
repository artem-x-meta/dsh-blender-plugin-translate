import fs from 'node:fs';
import path from 'node:path';
import { pyModuleFile, ASSEMBLY_PATH, AUDIT_PATH, BLOCKOUT_PATH, CALIB_PATH, CLEARANCE_PATH, CONTRACT_PATH, DELIVER_PATH, EVALHARNESS_PATH, FACE_PATH, FIX_PATH, GATE_PATH, GENERATOR_PATH, HUMAN_PATH, IMG_PATH, MATERIAL_PATH, MONTAGE_PATH, MOTION_PATH, PERF_PATH, PIPELINE_PATH, PLANNER_PATH, PRESET_PATH, PRINT_PATH, QC_PATH, QC_RENDER_PATH, RENDER_GUARD_PATH, RUNNER_PATH, SCULPT_PATH, SHAPESOLVE_PATH, SHAPE_PATH, SURFACE_PATH, SWEEP_PATH, TXN_PATH, UV_PATH, VEHICLE_PATH, VIEW_PATH, VISUALREPORT_PATH, KIT_HASH, } from '../../paths.js';
import { slipFixPath } from '../output/index.js';
import { winToWsl, wslToWin } from '../../config.js';
import { KERNEL_BOOTSTRAP } from './bootstrap.js';
const MODULE_ATTR = {
    RUNNER_READY: 'dsh_loop_api',
    PERF_READY: 'dsh_perf_api',
    VIEW_READY: 'dsh_view_api',
    CONTRACT_READY: 'dsh_contract_api',
    PLAN_READY: 'dsh_plan_api',
    TXN_READY: 'dsh_txn_api',
    QC_READY: 'dsh_qc_api',
    GEO_READY: 'dsh_geo_api',
    QC_RENDER_READY: 'dsh_qc_render_api',
    PRESET_READY: 'dsh_preset_api',
    AUDIT_READY: 'dsh_audit_api',
    MONTAGE_READY: 'dsh_montage_api',
    MOTION_READY: 'dsh_motion_api',
    DELIVER_READY: 'dsh_deliver_api',
    GENERATOR_READY: 'dsh_generator_api',
    SCULPT_READY: 'dsh_sculpt_api',
    FIX_READY: 'dsh_fix_api',
    UV_READY: 'dsh_uv_api',
    PRINT_READY: 'dsh_print_api',
    SWEEP_READY: 'dsh_sweep_api',
    MATERIAL_READY: 'dsh_material_api',
    RENDER_GUARD_READY: 'dsh_render_guard',
    GATE_READY: 'dsh_gate_api',
    IMG_READY: 'dsh_img_api',
    CALIB_READY: 'dsh_calib_api',
    FACE_READY: 'dsh_face_api',
    HUMAN_READY: 'dsh_human_api',
    CLEARANCE_READY: 'dsh_clearance_api',
    VEHICLE_READY: 'dsh_vehicle_api',
    SHAPE_READY: 'dsh_shape_api',
    PIPELINE_READY: 'dsh_pipe_api',
    ASSEMBLY_READY: 'dsh_assembly_api',
    BLOCKOUT_READY: 'dsh_blockout_api',
    VISUALREPORT_READY: 'dsh_visualreport_api',
    SHAPESOLVE_READY: 'dsh_shapesolve_api',
    EVALHARNESS_READY: 'dsh_evalharness_api',
    SURFACE_READY: 'dsh_surface_api',
};
/** Read the source of a python module under runtime (used for preload / job script assembly) */
export function readModuleSource(name) {
    return fs.readFileSync(pyModuleFile(name), 'utf8');
}
/**
 * v0.9.1 (93-B3): script path resolution. headless `file=` means **.blend** (passing a .py out of old habit gets
 * `File format is not supported`); now: `scriptFile=` explicitly accepts .py; passing a .py as `file=` automatically treats it as a script and says so.
 * Windows paths (D:\ or \\wsl.localhost\) and WSL paths (/home/...) are both accepted.
 */
export function readScriptPath(p) {
    const s = slipFixPath(String(p), null); // v0.9.6 field feedback: a WSL path missing the leading / is corrected first
    const isWin = /^[A-Za-z]:[\\/]/.test(s) || s.slice(0, 2) === '\\\\';
    return { win: isWin ? s : wslToWin(s), wsl: isWin ? winToWsl(s) : s };
}
/**
 * v0.9.0: preloading several modules requires each to get its own namespace.
 * The old implementation **pasted several module sources into one globals**, and every runtime module defines _j/_kernel/_store/_now →
 * so the later module overwrote the earlier one's helpers. Measured in practice: `preload="txn,deliver"` crashed txn outright (KeyError: 'marks').
 * Approach: exec each module into its own dict; private names (leading _) do not leak, public names and common imports are copied back into globals as before
 * (backwards compatible: code that called public functions like `dsh_loop_start` / `audit_mesh` directly still works).
 * The trailing `K.dsh_x_api = {...}` in a module goes through the real dsh_rt_kernel module object → the API still lands on K.
 */
export function preloadChunk(name) {
    const clean = String(name).trim().replace(/\.py$/, '');
    const file = pyModuleFile(clean);
    const src = fs.readFileSync(file, 'utf8');
    const ns = '__dsh_ns_' + clean.replace(/[^A-Za-z0-9_]/g, '_');
    return [
        '# ---- preload ' + clean + '.py (own namespace: private helpers do not overwrite each other)----',
        ns + ' = {"__name__": ' + JSON.stringify(clean) + ', "__file__": ' + JSON.stringify(file) + '}',
        'exec(compile(' +
            JSON.stringify(src) +
            ', ' +
            JSON.stringify(clean + '.py') +
            ', "exec"), ' +
            ns +
            ')',
        'globals().update({k: v for k, v in ' + ns + '.items() if not k.startswith("_")})',
    ].join(String.fromCharCode(10));
}
export async function injectModule(deps, file, marker, versionExpr = '1', prelude = '') {
    const attr = MODULE_ATTR[marker] || 'dsh_' + String(marker).toLowerCase() + '_api';
    const hashAttr = attr + '_fp';
    // Content fingerprint (size + mtime): when a module file changes, the next call re-injects automatically — essential for the dev loop.
    // Note: K survives a backend restart, so "only check hasattr" left edited files without effect (fixed in v0.7.0).
    let fp;
    try {
        const st = fs.statSync(file);
        fp = String(st.size) + '-' + String(Math.round(st.mtimeMs)) + '-k' + KIT_HASH;
    }
    catch (e) {
        fp = 'missing-k' + KIT_HASH;
    }
    // K is the source of truth: K is emptied after a Blender restart, so a local Set alone would wrongly report "already injected"
    try {
        // noMark: loading a python module is pure plumbing and cannot change the scene — it must not take part in the stale decision
        const chk = await deps.addon.send('execute_code', {
            code: KERNEL_BOOTSTRAP +
                '\nprint("HAVE " + str(hasattr(K, "' +
                attr +
                '")) + " FP " + str(getattr(K, "' +
                hashAttr +
                '", "none")))',
        }, 30000, { noMark: true });
        const chkRec = chk !== null && typeof chk === 'object' ? chk : null;
        const t = chkRec && typeof chkRec.result === 'string' ? chkRec.result : '';
        if (t.includes('HAVE True') && t.includes(fp)) {
            deps.injected.add(file);
            return true;
        }
        deps.injected.delete(file);
    }
    catch (e) {
        /* probe failed → re-inject */
    }
    const src = fs.readFileSync(file, 'utf8');
    const tail = '\nK.' +
        hashAttr +
        ' = ' +
        JSON.stringify(fp) +
        '\nprint("' +
        marker +
        ' v%d" % ' +
        versionExpr +
        ')';
    const out = await deps.addon.send('execute_code', {
        code: KERNEL_BOOTSTRAP +
            '\n__file__ = ' +
            JSON.stringify(file) +
            '\n' +
            (prelude ? prelude + '\n' : '') +
            src +
            tail,
    }, 60000, { noMark: true });
    const outRec = out !== null && typeof out === 'object' ? out : null;
    const txt = outRec && typeof outRec.result === 'string' ? outRec.result : '';
    if (!txt.includes(marker))
        throw new Error(path.basename(file) + ' injection failed: ' + txt.slice(0, 200));
    deps.injected.add(file);
    return true;
}
export function needFile(f, what) {
    if (!fs.existsSync(f))
        throw new Error(what + ' module is not in place yet: ' + path.basename(f) + ' (in development as of v0.9.0)');
    return f;
}
const ensureRunner = (d) => injectModule(d, RUNNER_PATH, 'RUNNER_READY', 'RUNNER_VERSION');
const ensurePerf = (d) => injectModule(d, PERF_PATH, 'PERF_READY', 'PERF_VERSION');
const ensureView = (d) => injectModule(d, VIEW_PATH, 'VIEW_READY', 'VIEW_VERSION');
const ensureContract = (d) => injectModule(d, CONTRACT_PATH, 'CONTRACT_READY', 'CONTRACT_VERSION');
const ensurePlanner = (d) => injectModule(d, PLANNER_PATH, 'PLAN_READY', 'PLAN_VERSION');
const ensureTxn = (d) => injectModule(d, TXN_PATH, 'TXN_READY', 'TXN_VERSION');
const ensureQc = (d) => injectModule(d, QC_PATH, 'QC_READY', 'QC_VERSION');
const ensureQcRender = (d) => injectModule(d, QC_RENDER_PATH, 'QC_RENDER_READY', 'QC_RENDER_VERSION');
const ensurePreset = (d) => injectModule(d, PRESET_PATH, 'PRESET_READY', 'PRESET_VERSION');
const ensureAudit = (d) => injectModule(d, AUDIT_PATH, 'AUDIT_READY', 'AUDIT_VERSION');
const ensureMontage = (d) => injectModule(d, MONTAGE_PATH, 'MONTAGE_READY', 'MONTAGE_VERSION');
const ensureMotion = (d) => injectModule(d, needFile(MOTION_PATH, 'motion'), 'MOTION_READY', 'MOTION_VERSION');
const ensureDeliver = (d) => injectModule(d, needFile(DELIVER_PATH, 'deliver'), 'DELIVER_READY', 'DELIVER_VERSION');
const ensureGenerator = (d) => injectModule(d, needFile(GENERATOR_PATH, 'generator'), 'GENERATOR_READY', 'GENERATOR_VERSION');
// v0.9.6 (upstream integration): the five new modules all go through needFile — a clear error when the file is not on disk yet, instead of ENOENT
const ensureSculpt = (d) => injectModule(d, needFile(SCULPT_PATH, 'sculpt'), 'SCULPT_READY', 'SCULPT_VERSION');
const ensureFix = (d) => injectModule(d, needFile(FIX_PATH, 'mesh_fix'), 'FIX_READY', 'FIX_VERSION');
const ensureUv = (d) => injectModule(d, needFile(UV_PATH, 'uv_tools'), 'UV_READY', 'UV_VERSION');
const ensurePrint = (d) => injectModule(d, needFile(PRINT_PATH, 'printcheck'), 'PRINT_READY', 'PRINT_VERSION');
const ensureSweep = (d) => injectModule(d, needFile(SWEEP_PATH, 'sweep'), 'SWEEP_READY', 'SWEEP_VERSION');
const ensureMaterial = (d) => injectModule(d, needFile(MATERIAL_PATH, 'material'), 'MATERIAL_READY', 'MAT_VERSION');
// The gate package calls other modules according to the spec: prepare the common few first (each injected once, then cached)
const ensureImg = (d) => injectModule(d, needFile(IMG_PATH, 'imgtools'), 'IMG_READY', 'IMG_VERSION');
// human_spec needs imgtools to measure the reference image ⇒ keep it in the chain
const ensurePipeline = (d) => injectModule(d, needFile(PIPELINE_PATH, 'pipeline'), 'PIPELINE_READY', 'PIPE_VERSION');
const ensureAssembly = (d) => injectModule(d, needFile(ASSEMBLY_PATH, 'assembly'), 'ASSEMBLY_READY', 'ASSEMBLY_VERSION');
const ensureBlockout = (d) => injectModule(d, needFile(BLOCKOUT_PATH, 'blockout'), 'BLOCKOUT_READY', 'BLOCKOUT_VERSION');
const ensureVisualReport = (d) => injectModule(d, needFile(VISUALREPORT_PATH, 'visualreport'), 'VISUALREPORT_READY', 'VISUALREPORT_VERSION');
const ensureShapesolve = (d) => injectModule(d, needFile(SHAPESOLVE_PATH, 'shapesolve'), 'SHAPESOLVE_READY', 'SHAPESOLVE_VERSION');
const ensureEvalharness = (d) => injectModule(d, needFile(EVALHARNESS_PATH, 'evalharness'), 'EVALHARNESS_READY', 'EVALHARNESS_VERSION');
const ensureSurface = (d) => injectModule(d, needFile(SURFACE_PATH, 'surface'), 'SURFACE_READY', 'SURFACE_VERSION');
const ensureShape = async (d) => {
    await ensureVehicle(d);
    return injectModule(d, needFile(SHAPE_PATH, 'shapegen'), 'SHAPE_READY', 'SHAPE_VERSION');
};
const ensureClearance = (d) => injectModule(d, needFile(CLEARANCE_PATH, 'clearance'), 'CLEARANCE_READY', 'CLEAR_VERSION');
// vehicle_sections needs imgtools' col_profile, and panels are usually followed by clearance acceptance ⇒ keep them in the chain
const ensureVehicle = async (d) => {
    await ensureImg(d);
    await ensureClearance(d);
    return injectModule(d, needFile(VEHICLE_PATH, 'vehicle'), 'VEHICLE_READY', 'VEHICLE_VERSION');
};
const ensureHuman = async (d) => {
    await ensureImg(d);
    return injectModule(d, needFile(HUMAN_PATH, 'human'), 'HUMAN_READY', 'HUMAN_VERSION');
};
const ensureFace = (d) => injectModule(d, needFile(FACE_PATH, 'faceeval'), 'FACE_READY', 'FACE_VERSION');
const ensureCalib = async (d) => {
    await ensureGate(d);
    return injectModule(d, needFile(CALIB_PATH, 'calib'), 'CALIB_READY', 'CALIB_VERSION');
};
const ensureGate = async (d) => {
    for (const f of [
        ensureAudit,
        ensurePrint,
        ensureUv,
        ensureMaterial,
        ensureFix,
        ensureHuman,
        ensureAssembly,
    ]) {
        try {
            await f(d);
        }
        catch (e) {
            /* one module failing to inject must not stop the whole package: the gate reports "that gate needs module X" per gate */
        }
    }
    return injectModule(d, needFile(GATE_PATH, 'gate'), 'GATE_READY', 'GATE_VERSION');
};
// The render guard must have the flag-file path injected (Windows form; the handler closure holds that namespace)
const ensureRenderGuard = (d, renderFlagWin) => injectModule(d, needFile(RENDER_GUARD_PATH, 'render_guard'), 'RENDER_GUARD_READY', 'RG_VERSION', 'DSH_RENDER_FLAG_WIN = ' + JSON.stringify(renderFlagWin));
export async function sceneEpoch(deps) {
    try {
        const out = await deps.addon.send('execute_code', { code: KERNEL_BOOTSTRAP + '\nprint("EPOCH " + _dsh_epoch_json())' }, 20000);
        const outRec = out !== null && typeof out === 'object' ? out : null;
        const t = outRec && typeof outRec.result === 'string' ? outRec.result : '';
        const l = t.split('\n').filter((x) => x.indexOf('EPOCH ') === 0);
        return l.length ? JSON.parse(l[l.length - 1].slice('EPOCH '.length)) : null;
    }
    catch (e) {
        return null;
    }
}
const createEnsures = (d, renderFlagWin) => ({
    ensureRunner: () => ensureRunner(d),
    ensurePerf: () => ensurePerf(d),
    ensureView: () => ensureView(d),
    ensureContract: () => ensureContract(d),
    ensurePlanner: () => ensurePlanner(d),
    ensureTxn: () => ensureTxn(d),
    ensureQc: () => ensureQc(d),
    ensureQcRender: () => ensureQcRender(d),
    ensurePreset: () => ensurePreset(d),
    ensureAudit: () => ensureAudit(d),
    ensureMontage: () => ensureMontage(d),
    ensureMotion: () => ensureMotion(d),
    ensureDeliver: () => ensureDeliver(d),
    ensureGenerator: () => ensureGenerator(d),
    ensureSculpt: () => ensureSculpt(d),
    ensureFix: () => ensureFix(d),
    ensureUv: () => ensureUv(d),
    ensurePrint: () => ensurePrint(d),
    ensureSweep: () => ensureSweep(d),
    ensureMaterial: () => ensureMaterial(d),
    ensureImg: () => ensureImg(d),
    ensurePipeline: () => ensurePipeline(d),
    ensureAssembly: () => ensureAssembly(d),
    ensureBlockout: () => ensureBlockout(d),
    ensureVisualReport: () => ensureVisualReport(d),
    ensureShapesolve: () => ensureShapesolve(d),
    ensureEvalharness: () => ensureEvalharness(d),
    ensureSurface: () => ensureSurface(d),
    ensureShape: () => ensureShape(d),
    ensureClearance: () => ensureClearance(d),
    ensureVehicle: () => ensureVehicle(d),
    ensureHuman: () => ensureHuman(d),
    ensureFace: () => ensureFace(d),
    ensureCalib: () => ensureCalib(d),
    ensureGate: () => ensureGate(d),
    ensureRenderGuard: () => ensureRenderGuard(d, renderFlagWin),
});
export function createKernelInternals(E) {
    const { RENDER_FLAG_WIN: renderFlagWin, addon, injected } = E;
    const d = { addon, injected };
    return {
        MODULE_ATTR,
        readModuleSource,
        readScriptPath,
        preloadChunk,
        injectModule: (file, marker, versionExpr = '1', prelude = '') => injectModule(d, file, marker, versionExpr, prelude),
        needFile,
        ...createEnsures(d, renderFlagWin),
        sceneEpoch: () => sceneEpoch(d),
    };
}
//# sourceMappingURL=api.js.map