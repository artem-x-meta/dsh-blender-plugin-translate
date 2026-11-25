/**
 * S6 · modeling class guide table ("which modeling type → first step + which ops to use + what not to hand-roll + acceptance gate")
 *
 * Why a separate table: catalog is a "capability family" view (audit/qc/vehicle/…); the model thinks "what am I building".
 * Measured lesson: another modeling AI had the vehicle_* recipes and knew Recipe 17/18/19, and still hand-wrote a parametric loft ⇒
 * one continuous smooth surface, no edges, no seams, 6 structural defects. The root cause is not missing docs, it is the missing
 * "entry + do-not-hand-roll + numerically judgeable acceptance gate".
 * This table writes those three down per **modeling class**, and lets the catalog be queried by class:
 *   blender_rt_plan(op="catalog", args={classes:true})         → all classes
 *   blender_rt_plan(op="catalog", args={class:"recon"})        → single class (entry/op chain/do-not-hand-roll/acceptance gate)
 * integrity is mechanically checked by tests/unit/js/contract/guidance.test.ts (a missing field / wrong op name goes red).
 */
export const MODELING_CLASS_GUIDE = [
    {
        c: 'recon',
        name: 'reference-image reconstruction (any object with a silhouette)',
        entry: 'blender_rt_plan(op="shape_draft", args={object_class:"aircraft|vehicle|rotational|furniture|hull|…"}) —— **S0 first emit the build sheet** (what it is / how big / how many pieces / main vs accessory / what shape / which parts bulge and which are concave); fill the sheet then op="shape_draft_check" to validate; **only after you have the reference image** use op="shape_plan" to get the section_path for that class',
        chain: 'shape_draft → shape_draft_check (mechanical sheet validation) → (after you have the image) shape_plan → img_rectify → shape_sections → shape_loft → crease_lines / inset_lines → shape_regions / shape_panels → qc_render_views(ref_path=…)',
        forbid: 'S0: do not measure mm, do not call audit_*/print_report to count objects and faces, do not freeze the numbers (dimensions only in tiers A–F, every item must carry evidence and to_confirm); do not hand-roll a loft, do not compute a station table by hand — hand-rolling only yields one continuous smooth surface (soap with no edges and no seams); the section path must use the section_path given by shape_plan',
        gate: 'S0: shape_draft_check ok=true (no mm-level absolute values, no empty fields); from S3 on: proportion gate (shape_package / vehicle_package) + three-view IoU + panel-seam and feature-line count > 0',
    },
    {
        c: 'faceted',
        name: 'faceted hard surface (armor plates / military models / mechanical panels)',
        entry: 'skill Recipe 2a (choose the form first)',
        chain: 'primitive/panel + boolean → bevel (2–3 segments, keep hard edges) → audit_mesh → clear_check (joined parts)',
        forbid: 'do not use SubSurf to smooth the edges away; do not fake panel seams by scaling panels',
        gate: 'audit_mesh sharp edges/normals + visible panel seams + no floating chunks (audit_connectivity)',
    },
    {
        c: 'smooth',
        name: 'smooth hard surface (sheet metal / rounded props)',
        entry: 'skill Recipe 2b',
        chain: 'primitive → Bevel (2 segments) → SubSurf(2) or crease_lines(radius_mm=…) → audit_mesh',
        forbid: 'do not push vertices by hand to make curvature; do not use shade smooth to fake fillets (a real radius needs Bevel/crease)',
        gate: 'no wrinkles/self-intersections + feature-line count > 0 + profile deviation (profile_diff)',
    },
    {
        c: 'organic',
        name: 'organic / character / prop volumes',
        entry: 'blender_rt_plan(op="sculpt_scan", args={objects:["…"]})',
        chain: 'sculpt_setup(mode="VOXEL", voxel_size="auto") → sculpt_apply(brush=draw|inflate|pinch|flatten|smooth|crease) → sculpt_filter / sculpt_remesh → audit_connectivity',
        forbid: 'do not assemble volumes with booleans; in headless do not try bpy.ops.sculpt.brush_stroke (it does not work through Blender 5.2 Python)',
        gate: 'connected components = 1 + envelope + normals pointing outward + (if printing) print_report',
    },
    {
        c: 'repeats',
        name: 'repeated array (tracks / chain links / heat fins)',
        entry: 'blender_rt_plan(op="generator_save", args={code:…}) or skill Recipe 6b (parametric pitch array)',
        chain: 'generator_save → generator_run(args=…) (change arguments, not code) or Array+Curve → audit_interference',
        forbid: 'do not copy-paste hard-coded parts (if changing an argument requires a code change, it is wrong)',
        gate: 'part count/pitch/gap numeric gate + zero interpenetration',
    },
    {
        c: 'boolean',
        name: 'boolean cutouts (wheel arches / vents / lightening holes)',
        entry: 'blender_rt_plan(op="destructive_guard", args={op:"boolean", targets:["…"]})',
        chain: 'destructive_guard → boolean → fix_repair (cleanup) → audit_interference',
        forbid: 'do not boolean on an unjudged connection (it will destroy the assembly relation)',
        gate: 'zero interpenetration + zero-area faces = 0 + connection not broken',
    },
    {
        c: 'human',
        name: 'human base mesh / head shape',
        entry: 'human_* base mesh and head shape (skill Recipe 15/16)',
        chain: 'human base mesh/head shape → sculpt_* refinement → audit_mesh → (assembly) clear_check',
        forbid: 'do not hand-roll a human proportion table; hide high-detail areas such as face and hands behind a mask and gloves',
        gate: 'proportion table + connectivity = 1 + no self-intersections',
    },
    {
        c: 'sweep',
        name: 'pipes / cables / rails / guardrails',
        entry: 'blender_rt_plan(op="sweep_analyze", args={path:[[…]], profile:{type:"circle", radius_mm:…}})',
        chain: 'sweep_analyze (compute the bend radius first) → sweep_build → audit_connectivity',
        forbid: 'do not join path segments by hand (bends that are too tight are rejected by default)',
        gate: 'bend radius > profile half-width + connected components = 1',
    },
    {
        c: 'rotational',
        name: 'surface of revolution (bottle / can / wheel hub / vase / nozzle)',
        entry: 'blender_rt_plan(op="shape_plan", args={object_class:"rotational"})',
        chain: 'shape_revolve(parts=[…]) → (wall thickness) print_report → material_*',
        forbid: 'do not loft — lofting an axisymmetric part is the wrong path (shape_plan says shape_revolve explicitly)',
        gate: 'axis-of-revolution deviation + wall thickness (take the resolution_mm warning from print_report seriously)',
    },
    {
        c: 'plate',
        name: 'plates / profiles / airfoils (cambered or left-right asymmetric)',
        entry: 'blender_rt_plan(op="shape_plan", args={object_class:"aircraft|hull"})',
        chain: 'shape_sections → section_outline (explicit closed profile) or superellipse section_pts + crease_lines → shape_loft',
        forbid: 'do not express camber with a left-right mirror (an airfoil must use section_outline)',
        gate: 'profile deviation (profile_diff) + IoU + feature-line count',
    },
    {
        c: 'assembly',
        name: 'assembly / mechanism / articulation',
        entry: 'blender_rt_plan(op="gate_plan", args={preset:"assembly"})',
        chain: 'mate_check / fit_help → motion_joints → motion_measure → motion_export_urdf; overall acceptance gate_run(spec_path=…)',
        forbid: 'do not hand-write acceptance criteria (read the three-state verdict at the top level)',
        gate: 'gate_run verdict ∈ pass/degraded/refuted (degraded ≠ pass)',
    },
    {
        c: 'deliver',
        name: 'printability / delivery',
        entry: 'blender_rt_plan(op="print_report", args={objects:["…"], min_mm:1.2, max_angle_deg:45})',
        chain: 'uv_* → material_* → material_bake → deliver_export → deliver_verify',
        forbid: 'do not hand-write the export, do not deliver just a .blend (delivery needs OBJ/MTL + manifest md5)',
        gate: 'manifest md5 cross-check + resolution_mm warning + UV zero-area faces = 0',
    },
];
/** short render of a single class (the model can read it on one screen: entry → chain → forbidden → gate) */
export function renderClassText(r) {
    const L = [];
    L.push('modeling class: ' + r.name + ' (class=' + r.c + ')');
    L.push('first step: ' + r.entry);
    L.push('op chain: ' + r.chain);
    L.push('do not hand-roll: ' + r.forbid);
    L.push('acceptance gate: ' + r.gate);
    return L.join(String.fromCharCode(10));
}
/** for the mechanical check: a class with a missing field goes red in the guidance contract test */
export function classGuideStats() {
    const need = ['c', 'name', 'entry', 'chain', 'forbid', 'gate'];
    const missing = [];
    for (const r of MODELING_CLASS_GUIDE) {
        for (const k of need)
            if (!r[k] || !String(r[k]).trim())
                missing.push(r.c + '.' + k);
    }
    return {
        classes: MODELING_CLASS_GUIDE.length,
        keys: MODELING_CLASS_GUIDE.map((r) => r.c),
        missing,
    };
}
/** model-facing tool list (15; blender_rt_pick removed in v2.3) —— matched name by name against capability.lock.json (guarded by the guidance contract test) */
export const MODEL_FACING_TOOLS = [
    'blender_rt_see',
    'blender_rt_do',
    'blender_rt_watch',
    'blender_rt_loop',
    'blender_rt_cmd',
    'blender_rt_commands',
    'blender_rt_perf',
    'blender_rt_opt',
    'blender_rt_headless',
    'blender_rt_plan',
    'blender_rt_worker',
    'blender_rt_txn',
    'blender_rt_preset',
    'blender_rt_job',
    'blender_viewport',
];
/**
 * Subagent handoff block (S6-b) —— the main model pastes it **verbatim into the subagent prompt**.
 *
 * Why it is required: subagents have a self-contained context (they cannot see the catalog the main model read), and they tend to
 * write Python directly to bypass the plan channel; the measured consequence is exactly "no vehicle_*, a hand-rolled loft instead
 * → one smooth surface with no edges and no seams".
 * Goal: **short** (it fits into a subagent prompt), **only what is needed to decide** (class→first step→do not hand-roll + tool names
 * + hard rules + channel discipline).
 */
export function renderHandoff() {
    const L = [];
    L.push('# Blender tool map (subagent must read · 30 seconds)');
    L.push('');
    L.push('**Do not guess tools**: run `blender_rt_plan(op="catalog")` first to see the 28 capability families; query by modeling class with `args={classes:true}` (or a single class with `args={class:"recon"}`).');
    L.push('model-facing tools, ' + String(MODEL_FACING_TOOLS.length) + ' of them: ' + MODEL_FACING_TOOLS.join(' '));
    L.push('');
    L.push('## 12 modeling classes: first step | do not hand-roll');
    L.push('');
    for (const r of MODELING_CLASS_GUIDE) {
        L.push('- **' + r.c + '** (' + r.name + '): ' + r.entry + ' | forbidden: ' + r.forbid);
    }
    L.push('');
    L.push('## Three hard rules');
    L.push('1. Reference-image reconstruction **starts with the S0 draft**: `shape_draft` emits the build sheet (judge only what it is / how big / how many pieces / main vs accessory / what shape / which parts bulge and which are concave, **do not measure mm, do not count mesh**) → `shape_draft_check` mechanical validation; **after you have the image** call `shape_plan(object_class=…)` to get `section_path`, do not hand-roll the section, do not compute the station table by hand;');
    L.push('2. For car shells and housings **hand-rolling a loft is forbidden** (hand-rolling only yields one continuous smooth surface, no edges, no seams); panel seams and edge lines use `vehicle_panels` + `crease_lines`/`inset_lines`;');
    L.push('3. Acceptance is always a **mechanical gate** (`gate_run` top-level three-state verdict; `degraded` ≠ pass), never a substitute like "looks right".');
    L.push('');
    L.push('## Geometry base geo (resident, do not write your own)');
    L.push('');
    L.push('KERNEL_BOOTSTRAP already injects geo (no preload needed):');
    L.push('build box/cyl/tube/prism/loft/stack | cut boolean (**with degeneracy guard**), hole_cut/slots_cut (batch in one boolean) | group mirror/linear_array/join | finish edges bevel/shade_auto (**auto-smooth without changing topology**) | measure mesh_stats/tri_count/bbox_all | inspect quick_views | register own(ob,coll,owner) (COL_/dsh.owner)');
    L.push('**Verbs only, no nouns**: tooth pitch/station table/section/coordinates always come from spec.py.');
    L.push('Quick reference: help/selftest of K.dsh_geo_api; layering is in the header comment of runtime/py/geometry/geo.py.');
    L.push('');
    L.push('## Channel discipline');
    L.push('- Long jobs (>1 min / long renders / batch geometry) go through `blender_rt_job` / `blender_rt_headless`, do not block and wait synchronously;');
    L.push('- Scene writes allow **only one writer at a time** (write lease; returns 409 while another session holds it, read-only ops are exempt);');
    L.push('- Use `blender_rt_see` for look-after-each-change; measure with `img_*`/`audit_*`, **never eyeball it**.');
    L.push('');
    L.push('## Not covered by this plugin (do not look for tools here)');
    L.push('Biological/organic modeling: no loft/sculpt recipes → hand-write a bmesh loft + field sculpting (freeze the anatomical calibration in spec.py first); film-grade lighting/volumetrics/compositing: calibrate exposure and lights yourself; no character rigging.');
    L.push('');
    L.push('## Object ownership (second dimension of write scope: prefix + collection)');
    L.push('LGT-/LIGHT- → COL_Lights, CAM- → COL_Camera, GEO-VFX- → COL_VFX; if you only have write permission on a single collection, name by prefix and call K.route_collections() once before assembly.');
    return L.join(String.fromCharCode(10));
}
//# sourceMappingURL=classes.js.map
