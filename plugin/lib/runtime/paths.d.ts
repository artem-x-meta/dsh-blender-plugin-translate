/** Same directory as engine.mjs (runtime/) */
export declare const HERE: string;
/** Python asset root: in the source tree = runtime/; in build output = the package-root runtime/ (two levels up from lib/runtime/*.js) */
export declare const PY_ROOT: string;
export declare const ADDRESS: {
    host: string;
    port: number;
};
export declare const WIN_TMP: string;
export declare const WSL_TMP: string;
export declare const LIVE_PNG_WIN: string;
export declare const LIVE_PNG_WSL: string;
/**
 * Express a host-side path in the form the Blender process sees.
 * Windows: path.win32.join (backslashes + drive letter); WSL: wslToWin; macOS: identity (same machine, same OS).
 * macOS support: the scattered path.win32.join calls used to produce garbage strings like \Users\... on mac;
 * they are all funneled through here so none get missed again.
 */
export declare function blenderJoin(...parts: string[]): string;
export declare const PY_DOMAINS: string[];
/** Public module name -> runtime/py/<domain>/<name>.py (the single registry source is modules.json). */
export declare function pyModuleFile(name: unknown): string;
/** All public module names (listed when preload fails; does not change with the filesystem). */
export declare function pyModuleNames(): string[];
export declare function pyModuleExists(name: unknown): boolean;
/** Shared kernel (kit): the single implementation of JSON/API boilerplate, units, geometry, measurement and receipt skeletons */
export declare const KIT_PATH: string;
/** Geometry base (geo): the **mechanism layer** - boolean/hole/slot/mirror/array/extrude/loft/bevel/auto-smooth.
 *  Verbs only, no nouns (contains no shape defaults); guaranteed present by KERNEL_BOOTSTRAP like kit. */
export declare const GEO_PATH: string;
export declare const RUNNER_PATH: string;
export declare const PERF_PATH: string;
export declare const VIEW_PATH: string;
/** Contract layer: component/connection registry, envelope/interference/interface validation, destructive gating, evidence ledger, tri-state verdicts */
export declare const CONTRACT_PATH: string;
/** Planner: object graph -> diagnostics -> compile to bpy -> graph export */
export declare const PLANNER_PATH: string;
export declare const WORKER_PATH: string;
export declare const TXN_PATH: string;
/** Built-in QC (v0.7.0): masks / IoU / profiles / comparison images + inner-loop measure presets */
export declare const QC_PATH: string;
/** Render harness (v0.8.8): auto framing + fixed three-point lighting + per-image jsonl timing + budget verdict */
export declare const QC_RENDER_PATH: string;
/** Preset library (v0.8.2): save / apply / export parameter combinations */
export declare const PRESET_PATH: string;
/** Mesh audit (wired up in v0.9.0): audit_* prefixed ops go here.
 *  Before this, audit.py only existed on the preload path, while the documented blender_rt_plan(op="audit_mesh") in docs had no route at all. */
export declare const AUDIT_PATH: string;
/** Montage (wired up in v0.9.0): the montage op goes here (evidence tier L2: a cropped montage as the few cells for the eye) */
export declare const MONTAGE_PATH: string;
/** Articulation/mechanisms (v0.9.0): joint measurement + sweep validation + URDF/USDA export (motion_* prefixed ops) */
export declare const MOTION_PATH: string;
/** Delivery export (v0.9.0): unit-box normalization + multiple OBJ/MTL sets + manifest(md5) (deliver_* prefixed ops) */
export declare const DELIVER_PATH: string;
/** Generator registry (v0.9.0 · #18, a lightweight Blender-native version of the codified-modeling channel): now part of the geometry domain package. */
export declare const GENERATOR_PATH: string;
/** Procedural sculpting (v0.9.6 · upstream integration): sculpt_* prefixed ops go here.
 *  Neither upstream project can do procedural sculpting (blend-ai says it cannot simulate brush strokes; mcp-for-blender has no sculpting),
 *  so this module uses numpy displacement brushes + topology prep + masks to turn "sculpting" into recomputable geometry operations. */
export declare const SCULPT_PATH: string;
/** Mesh repair loop (v0.9.6 · upstream integration): fix_* prefixed ops - audit only diagnoses, this one heals. */
export declare const FIX_PATH: string;
/** UV quartet (v0.9.6 · upstream integration): now part of the geometry domain package. */
export declare const UV_PATH: string;
/** Manufacturing checks (v0.9.6 · upstream integration): print_* prefixed ops (thin walls / overhangs / shells / summary). */
export declare const PRINT_PATH: string;
/** Sweep along path (v0.9.6 · upstream integration): sweep_* prefixed ops (pipes/cables/tracks + bend radii computed before building). */
export declare const SWEEP_PATH: string;
/** Material node graphs (v0.9.6): material_* prefixed ops - measured 2,732 node links / 204 scripts reinventing the wheel */
export declare const MATERIAL_PATH: string;
/** Render state tracking (v0.9.6): write a disk marker when rendering starts and delete it when done; the backend reads that file for an instant busy verdict */
export declare const RENDER_GUARD_PATH: string;
/** Spec-driven gate package (v0.9.6 · field feedback #3): one spec runs all gates (tri-state verdict) */
export declare const GATE_PATH: string;
/** Reference-image gauge (integration plan): measure to numbers / crop and zoom / draw back / diff */
export declare const IMG_PATH: string;
/** Gate calibration suite: inject 8 defect classes and see how many the gates catch + healthy baseline comparison */
export declare const CALIB_PATH: string;
/** Face proportion gate: landmarks -> 6 dimensionless ratios -> difference against classical/reference values */
export declare const FACE_PATH: string;
/** Humanoid base mesh (zero assets): joint coordinates + radii -> Skin+Subsurf -> a proportionally correct dummy */
export declare const HUMAN_PATH: string;
/** Pairwise clearance gate: rule-table-driven closest distance + interpenetration verdict */
export declare const CLEARANCE_PATH: string;
/** Vehicle shell: longitudinal profile -> loft into a shell (analytic wheel arches) + proportion gate */
export declare const VEHICLE_PATH: string;
/** Generic reference-image reconstruction method layer: category protocol + generic gauges/loft/fit/parting/revolve */
export declare const SHAPE_PATH: string;
/** Pipeline: artifact registry + step orchestration */
export declare const PIPELINE_PATH: string;
/** Assembly: manifest / all-pairs classification scan / merge / assembly gate */
export declare const ASSEMBLY_PATH: string;
/** Blockout: declarative blockout + 3 views + GLB export */
export declare const BLOCKOUT_PATH: string;
/** Same-camera QC visual report (verdict-first) */
export declare const VISUALREPORT_PATH: string;
/** Headless multi-view silhouette fitting (analytic projection, no rendering) */
export declare const SHAPESOLVE_PATH: string;
/** Defect injection/baseline replay evaluation (evalharness) */
export declare const EVALHARNESS_PATH: string;
/** Surface algorithm package: loft/sweep/patch/validate */
export declare const SURFACE_PATH: string;
/**
 * The user's Blender config directory (where GPU preferences live) - headless processes cannot see it by default, and Cycles silently falls back to CPU.
 * Defaults to null in the shared build (use the system default config); to inherit a particular config, set DSH_BLENDER_USER_CONFIG / the blenderUserConfig option.
 */
export declare const USER_CONFIG_WIN: string | null;
export declare const USER_SCRIPTS_WIN: string | null;
/** GPU prelude: configure the Cycles device inside the headless process and print the DSH_GPU receipt (see "GPU semantics" in the README) */
/**
 * Engine prelude (v0.8.0): defaults to **EEVEE + ray tracing**, optionally cycles (OptiX device prelude) / keep (leave untouched).
 * Why default to EEVEE: (1) it is a pure GPU renderer going through the graphics backend (OPENGL / RTX 4060 on this machine),
 *   and **does not depend on "preferences" like compute_device_type** -> in headless it will not silently fall back to CPU the way Cycles does;
 * (2) measured (360 objects / 350 meshes / 512×512 / 64 samples): EEVEE+RT warm frame **1.35 s** vs Cycles GPU **3.13 s** (2.3x);
 * (3) the cost: first-frame shader compilation ~16 s -> for iteration use a hot blender_rt_worker session (compile once, then 1.35 s per frame).
 * The receipt marker stays DSH_GPU (for compatibility) and carries engine / backend / renderer / rt state.
 */
export declare const GPU_PRELUDE: string;
/** Custom-view render output (overwrites this file by default) */
export declare const VIEW_PNG_WIN: string;
export declare const VIEW_PNG_WSL: string;
/** Headless Blender executable (WSL-side path; spawn goes through binfmt to start a Windows process); when it is missing the tool reports setup guidance */
export declare const BLENDER_EXE: string | null;
export { PKG_ROOT } from './config.js';
export declare const PATH_HELPERS: string;
/** act wrapper: returns partial stdout/stderr/traceback even on exceptions (v0.7.0) */
export declare const ACT_WRAPPER: (src: string) => string;
export declare const KIT_SRC: string;
export declare const KIT_HASH: string;
export declare const GEO_SRC: string;
export declare const GEO_HASH: string;
