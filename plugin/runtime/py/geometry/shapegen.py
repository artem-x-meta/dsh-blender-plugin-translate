# -*- coding: utf-8 -*-
"""DSH generic reference-image reconstruction (P4): a method layer "envelope → station table → section → feature lines → acceptance" that is **independent of the object class**.

This layer does not re-implement geometry:
  * measuring (station table/section outline/envelope) → reuses vehicle_sections (it already measures the outline column by column / row by row, nothing "vehicle" about it)
  * lofting (station table + section + feature lines + bevel) → reuses vehicle_loft
  * parameterisation (polyline family + K scan) → reuses vehicle_fit(family="polyline")
  * multiple volumes / seams → reuses vehicle_regions / vehicle_panels
What this layer owns is the **method**: per object class, which views are needed, which ratios to watch, which operators to pair, how to accept.

ops:
    shape_plan(object_class)   — the reconstruction protocol for that class (views/ratios/operators/acceptance/traps)
    shape_sections(...)        — three views → station table + section outline + envelope (generic measuring tool)
    shape_loft(...)            — station table → loft (section outline + feature lines + bevel)
    shape_fit(...)             — station table → polyline-family parameterisation (family=polyline by default, K scan)
    shape_regions / shape_panels — multiple volumes / split along seams
    shape_selftest / shape_help

⚠ Applicability boundary (written into shape_help too): it fits any object that "has a clear outer silhouette and can be described with orthographic views";
it does not fit: things without an outer silhouette (cloth/fur/fluid/smoke), things defined by internal structure (porous lattices/topology-optimised parts).
"""
import json

SHAPE_VERSION = 2  # v2: adds the S0 draft assessment (shape_draft / shape_draft_check)

# class → reconstruction protocol. In views, s/f/t = side/front/top view; ratios = the proportions to hold; ops = the operators to pair
CLASSES = {
    "vehicle": {
        "views": "s f t", "symmetric": "both sides", "volumes": "single/multiple volumes", "ground": "wheels or tracks touching the ground",
        "ratios": ["wheel diameter/vehicle height WBR", "wheelbase/vehicle length", "height/length", "track/vehicle width", "front and rear overhang", "ground clearance"],
        "ops": ["img_rectify", "vehicle_sections", "vehicle_package", "vehicle_loft", "vehicle_regions",
                "vehicle_panels", "vehicle_fit", "clear_check"],
        "gates": ["vehicle_package every item passes", "clear_check zero interpenetration + consistent seam width", "qc_render_views three-view IoU"],
        "traps": ["wheel diameter cannot be derived from the filled silhouette (needs wheel_r_px)", "no top view ⇒ the body comes out too narrow", "photos must have the perspective corrected first"],
    },
    "humanoid": {
        "views": "s f", "symmetric": "both sides", "volumes": "single (with split parts)", "ground": "both feet touching the ground",
        "ratios": ["head-to-body ratio heads (7–8)", "shoulder width/head height (≈1.5)", "elbow/knee position (0.5/0.75 of the stance)"],
        "ops": ["human_spec", "human_base", "human_head", "human_measure", "face_ratios", "motion_joints"],
        "gates": ["difference between human_measure's heads/shoulder_over_head and the spec", "face_ratios tolerance", "motion_joints joints are movable"],
        "traps": ["a realistic face with zero assets is not achievable ⇒ cover it with a mask/helmet", "joint markers are the only reliable mounting datum"],
    },
    "creature": {
        "views": "s f t", "symmetric": "both sides", "volumes": "single", "ground": "quadruped/multiped touching the ground",
        "ratios": ["body length/shoulder height", "head length/body length", "limb segment proportions"],
        "ops": ["shape_sections", "shape_loft", "shape_fit", "audit_connectivity"],
        "gates": ["station-table IoU", "silhouette IoU against the reference ≥0.8"],
        "traps": ["quadrupeds and bipeds cannot share one set of ratios", "fur is not covered by this method (no outer silhouette)"],
    },
    "headwear": {
        "views": "s f t", "symmetric": "both sides", "volumes": "single (shell)", "ground": "none",
        "ratios": ["head height/head width/head depth (233:175:206 reference)", "eye line 0.50 / nose base 0.725 / mouth line 0.825"],
        "ops": ["human_head", "face_ratios", "shape_loft", "print_report"],
        "gates": ["3D ratios agree with the landmarks", "print_report wall thickness (when printing)"],
        "traps": ["leave head-circumference allowance in the cavity; do not forget the ear/neck openings"],
    },
    "furniture": {
        "views": "s f", "symmetric": "both sides", "volumes": "multiple volumes (seat/back/legs)", "ground": "four legs touching the ground",
        "ratios": ["seat height/total height", "seat depth/total depth", "backrest tilt (°)", "leg spacing"],
        "ops": ["shape_sections", "shape_loft", "shape_regions", "sweep_build", "print_report", "clear_check"],
        "gates": ["key dimensions (seat height/seat depth) ±2%", "no interpenetration between legs and seat", "pass print_report if printing"],
        "traps": ["ergonomic dimensions outrank shape similarity", "multiple volumes must be built as separate parts and then assembled"],
    },
    "hull": {
        "views": "s t", "symmetric": "both sides", "volumes": "single", "ground": "waterline",
        "ratios": ["length/beam", "depth/length", "sections differ above/below the waterline"],
        "ops": ["shape_sections", "shape_loft", "shape_fit", "print_report"],
        "gates": ["width matches at the waterline", "side-view silhouette IoU"],
        "traps": ["give **separate** station tables above and below the waterline (the section jumps)", "a top view is mandatory (it decides the beam distribution)"],
    },
    "aircraft": {
        "views": "s f t", "symmetric": "both sides", "volumes": "multiple volumes (fuselage/wings/tail)", "ground": "landing gear",
        "ratios": ["wingspan/fuselage length", "wing chord distribution", "fuselage height/width", "tail area ratio"],
        "ops": ["shape_sections", "shape_loft", "shape_regions", "sweep_build", "clear_check"],
        "gates": ["three-view IoU (top view matters most)", "no interpenetration at the wing/fuselage joint"],
        "traps": ["wings need an **airfoil section** (shape supplies the profile points), not a superellipse", "dihedral/sweep are independent parameters"],
    },
    "rotational": {
        "views": "s (single profile)", "symmetric": "axisymmetric", "volumes": "single", "ground": "none",
        "ratios": ["height/diameter", "position of the maximum diameter", "neck/opening ratio"],
        "ops": ["img_scan", "shape_revolve", "print_report"],
        "gates": ["silhouette IoU", "the revolved body is closed (audit_mesh finds no non-manifold)"],
        "traps": ["**do not loft**: a rotational body (bottle/can/hub/vase) must **revolve** a single profile around the axis"],
    },
    "weapon": {
        "views": "s t", "symmetric": "single side/both sides", "volumes": "multiple volumes", "ground": "none",
        "ratios": ["overall length", "grip position/length", "barrel/receiver ratio"],
        "ops": ["shape_sections", "shape_loft", "shape_regions", "clear_check"],
        "gates": ["overall length and grip-point dimensions", "moving-part clearance (clear_check min_mm)"],
        "traps": ["grip dimensions are a hard constraint (hand width/finger position)", "moving parts need travel clearance"],
    },
    "generic": {
        "views": "s f (+t strongly recommended)", "symmetric": "as built", "volumes": "as built", "ground": "as built",
        "ratios": ["first measure the three envelope ratios length/width/height, then fix the ratios specific to the class"],
        "ops": ["img_rectify", "shape_sections", "shape_loft", "shape_fit", "img_diff", "audit_mesh"],
        "gates": ["three-view IoU", "envelope dimension error ≤2%"],
        "traps": ["correct the photo's perspective first", "without a top view there is no plan-view taper"],
    },
}

# ── Section-path selection (**the only routing basis**: shape_plan hands it out together with the protocol)
SECTION_PATH = {
    "vehicle": "section_shape (front view, width row by row → mirror symmetry); wide-body kits/asymmetric parts use section_outline; wheels/hubs use shape_revolve",
    "humanoid": "human_base brings its own volumes; use section_shape when torso/limb cross-sections must be exact",
    "creature": "section_shape (side view gives the outline, top view gives the half-width); asymmetric parts such as horns/beaks use section_outline",
    "headwear": "section_shape (symmetric shell); asymmetric parts such as brims/goggles use section_outline; start a helmet cavity with shape_revolve",
    "furniture": "section_outline (legs/backrests are mostly rectangular or irregular sections); tubes go through sweep_build; split seat/backrest with shape_regions",
    "hull": "section_shape (top view gives the half-width) **give separate station tables above and below the waterline**; bodies of revolution such as bulbous bows use shape_revolve",
    "aircraft": "**section_outline (airfoil, mandatory)** — the mirror-symmetry path cannot express camber; fuselage uses section_shape; engine nacelles use shape_revolve",
    "rotational": "**shape_revolve (not a loft)**: bottle/can/hub/vase/nozzle; several parts use shape_revolve(parts=[...])",
    "weapon": "section_outline (receivers/fore-ends are mostly rectangular or irregular); barrels/mag wells use shape_revolve; grips use section_outline",
    "generic": "section_shape by default; **camber / left-right asymmetry / exact section control ⇒ section_outline**; axisymmetric ⇒ shape_revolve",
}

DECISION = [
    "① axisymmetric (bottle/can/hub/vase/nozzle) ⇒ shape_revolve (profile revolved around the axis), **not** a loft",
    "② left-right symmetric with a visible front-view silhouette ⇒ section_shape (normalised width row by row, scaled by the station half-width)",
    "③ camber / left-right asymmetry / exact section control (airfoils, receivers, irregular parts) ⇒ section_outline (explicit closed outline)",
    "④ only one side profile and a cross-section that stays essentially constant along the length (plates, profiles) ⇒ superellipse section_pts + feature lines is enough",
    "⑤ multiple volumes (cab+box, fuselage+wings, hub+tyre) ⇒ shape_regions / shape_revolve(parts=[...]), then clear_check the clearances after assembly",
]

STEPS = [
    "⓪ draft assessment: shape_draft — only decide 'what it is / roughly how big (size class) / how many blocks / main parts and accessories / what shape / where it bulges or recesses', "
    "**no mm measuring, no mesh counting**; validate the filled table with shape_draft_check (refine it row by row once the images arrive)",
    "① correction: photo → img_rectify (orthographic three-views can skip it)",
    "② measure the envelope: length/width/height + the class's key ratios (pass the ratio gate first, otherwise do not go on)",
    "③ measure the station table: shape_sections (side view: lower/upper boundary per column + top view: half-width per column + front view: section outline)",
    "④ loft: shape_loft (station table sets the outline, section outline sets the character, feature lines set the surface feel)",
    "⑤ feature lines: crease_lines (hard crease / radius_mm bevel) + inset_lines (facet grooves)",
    "⑥ parameterisation (optional): shape_fit polyline family + K scan, giving a spec whose numbers can be edited",
    "⑦ multiple volumes/seams: shape_regions (each block becomes its own volume) + shape_panels (real seams)",
    "⑧ acceptance: three-view IoU (qc_render_views/img_diff) + numeric gates (dimensions/ratios/clearances)",
]


import sys as _sys_kit
_KIT = getattr(_sys_kit.modules.get("dsh_rt_kernel"), "dsh_kit", None)
if _KIT is None:
    raise RuntimeError("shapegen needs the shared kernel K.dsh_kit (injected by KERNEL_BOOTSTRAP)")


_j = _KIT.j  # shared kernel (the original built-in implementation has been removed, see S1)
_api = _KIT.api  # shared kernel
def shape_plan(object_class="generic", family=None):
    """The **reconstruction protocol** for this class: which views, which ratios to watch, which operators to pair, how to accept, which traps exist."""
    c = str(object_class or "generic").lower()
    if c not in CLASSES:
        return _j({"ok": False, "error": "unknown class object_class=%s" % object_class,
                   "classes": sorted(CLASSES)})
    row = dict(CLASSES[c])
    row["section_path"] = SECTION_PATH.get(c)
    return _j({"ok": True, "object_class": c, "plan": row,
               "steps": STEPS, "section_decision": DECISION, "families": sorted(CLASSES),
               "note": "this is a **method layer**: all geometry reuses the img_*/vehicle_* measuring, lofting, fitting and part-splitting operators;"
                       "switching class only switches the protocol (views/ratios/acceptance), never the mechanism"})


def shape_sections(**kw):
    """Generic measuring tool: three views → station table + section outline + envelope (delegates to vehicle_sections; wheel-axle detection only fires when wheels are present)."""
    api = _api("vehicle")
    if api is None:
        return _j({"ok": False, "error": "the vehicle module is required (add vehicle to the preload)"})
    out = api("sections", kw)
    out["layer"] = "shape/measure"
    return _j(out)


def shape_loft(**kw):
    """Generic loft: station table → shell (section outline + feature lines + bevel + wheel-arch flare). Delegates to vehicle_loft."""
    api = _api("vehicle")
    if api is None:
        return _j({"ok": False, "error": "the vehicle module is required"})
    out = api("loft", kw)
    out["layer"] = "shape/loft"
    return _j(out)


def shape_fit(**kw):
    """Generic parameterisation: station table → polyline family + K scan (family=polyline by default; it assumes nothing about "vehicles")."""
    api = _api("vehicle")
    if api is None:
        return _j({"ok": False, "error": "the vehicle module is required"})
    kw.setdefault("family", "polyline")
    out = api("fit", kw)
    out["layer"] = "shape/fit"
    return _j(out)


def shape_regions(**kw):
    """Generic multiple volumes: split by interval, each block its own volume. Delegates to vehicle_regions."""
    api = _api("vehicle")
    if api is None:
        return _j({"ok": False, "error": "the vehicle module is required"})
    out = api("regions", kw)
    out["layer"] = "shape/regions"
    return _j(out)


def shape_panels(**kw):
    """Generic part split: thin the plate at the given position ⇒ real seams, optionally separated into several parts. Delegates to vehicle_panels."""
    api = _api("vehicle")
    if api is None:
        return _j({"ok": False, "error": "the vehicle module is required"})
    out = api("panels", kw)
    out["layer"] = "shape/panels"
    return _j(out)


def shape_revolve(profile=None, name="Revolved", axis="Z", segments=48, angle_deg=360.0, parts=None):
    """**Rotational body** path (bottle/can/hub/vase): one profile revolved around the axis — do not loft this kind of object.

    profile = [[r_mm, z_mm], …] (the profile: radius → height), given bottom to top along z.
    """
    import bpy
    import bmesh as _bm
    import math
    if parts:
        # **multi-volume rotational part**: supply several {profile, at:[x,y,z]_mm, name, segments} at once
        # uses: hub+tyre, bottle+cap, nozzle arrays, flange groups — rotational bodies combined with multiple volumes
        out = []
        for i, q in enumerate(list(parts)):
            q = dict(q or {})
            at = q.get("at") or [0.0, 0.0, 0.0]
            r = json.loads(shape_revolve(profile=q.get("profile"), name=q.get("name") or ("%s_%d" % (name, i)),
                                         axis=q.get("axis") or axis,
                                         segments=int(q.get("segments") or segments),
                                         angle_deg=float(q.get("angle_deg") or angle_deg)))
            if not r.get("ok"):
                out.append({"name": q.get("name") or i, "ok": False, "error": r.get("error")})
                continue
            ob = bpy.data.objects.get(r.get("object"))
            if ob is not None:
                ob.location = (float(at[0]) / 1000.0, float(at[1]) / 1000.0, float(at[2]) / 1000.0)
            r["at_mm"] = [round(float(x), 2) for x in at]
            out.append(r)
        return _j({"ok": all(r.get("ok") for r in out), "parts": out, "count": len(out),
                   "note": "multi-volume rotational part: each part is its own object with its own placement; verify clearances with clear_check after assembly"})
    try:
        pts = [[float(q[0]) / 1000.0, float(q[1]) / 1000.0] for q in (profile or [])]
        if len(pts) < 2:
            return _j({"ok": False, "error": "profile needs at least two points [[r_mm, z_mm], …]"})
        nm = str(name or "Revolved")
        o0 = bpy.data.objects.get(nm)
        if o0 is not None:
            me0 = o0.data
            bpy.data.objects.remove(o0, do_unlink=True)
            if me0 is not None and me0.users == 0:
                bpy.data.meshes.remove(me0, do_unlink=True)
        bm = _bm.new()
        n = max(6, int(segments))
        sweep = max(1e-6, math.radians(float(angle_deg)))
        rings = []
        closed = abs(float(angle_deg) - 360.0) < 1e-6
        for i in range(n if closed else n + 1):
            th = sweep * i / float(n)
            ring = []
            for (r, z) in pts:
                if r <= 1e-9:
                    ring.append(bm.verts.new((0.0, 0.0, z)))
                else:
                    ring.append(bm.verts.new((r * math.cos(th), r * math.sin(th), z)))
            rings.append(ring)
        for k in range(len(rings) - 1 if not closed else len(rings)):
            a = rings[k]
            b = rings[(k + 1) % len(rings)]
            for i in range(len(a) - 1):
                try:
                    bm.faces.new((a[i], a[i + 1], b[i + 1], b[i]))
                except Exception:
                    pass
        _bm.ops.remove_doubles(bm, verts=bm.verts, dist=1e-6)
        _bm.ops.recalc_face_normals(bm, faces=bm.faces)
        me = bpy.data.meshes.new(nm)
        bm.to_mesh(me)
        bm.free()
        ob = bpy.data.objects.new(nm, me)
        bpy.context.scene.collection.objects.link(ob)
        d = [round(float(x) * 1000.0, 1) for x in ob.dimensions]
        return _j({"ok": True, "object": ob.name, "segments": n, "profile_pts": len(pts),
                   "size_mm": {"x": d[0], "y": d[1], "h": d[2]}, "vertices": len(ob.data.vertices),
                   "note": "rotational-body path: the profile comes from the reference outline (half the width of each row = radius)"})
    except Exception as e:
        return _j({"ok": False, "error": "%s: %s" % (type(e).__name__, str(e)[:220])})


# ── S0 rough assessment (draft recon) ★ the **first step** of reference-image reconstruction ────────────────────────────
# Motivation (a measured lesson): jumping straight into img_rectify/shape_sections to measure mm and running audit_* to count objects and faces
#   at a stage **where there is no reference image yet** amounts to treating invented numbers as the spec; once the images arrive it all gets thrown away.
# The right posture: "draft it in your head" first — only decide **what it is / roughly how big / how many blocks / what shape each one is / where it bulges or recesses in space**,
#   everything carries confidence and source, **unknown is allowed, hardcoding is forbidden**.
# This contract turns that step into something mechanically checkable:
#   R1 dimensions may only be log-scale classes A–F (absolute mm/cm values are rejected);
#   R2 calling audit_*/print_report (counting objects/faces) and the station-table measuring operators is forbidden at this stage;
#   R3 every field carries confidence + source, every part carries to_confirm (= what to fill in once the images arrive).
import re as _re

_DRAFT_MM_RE = _re.compile(r"\d+(\.\d+)?\s*(mm|millimeter|millimetre|cm|centimeter|centimetre)", _re.I)
_DRAFT_AUTO_RE = _re.compile(r"^[A-Za-z_]+\.\d{3}$")

DRAFT_STAGE = "S0"

SIZE_CLASSES = [
    {"id": "A", "range": "<10cm",   "anchor": "pocket-sized item (jewellery/part/lighter)"},
    {"id": "B", "range": "10–30cm", "anchor": "one-handed (pistol/controller/small prop)"},
    {"id": "C", "range": "0.3–1m",  "anchor": "two-handed or held in the arms (long gun/chair/small appliance)"},
    {"id": "D", "range": "1–3m",    "anchor": "one person tall to two people long (person/motorcycle/sofa/small boat)"},
    {"id": "E", "range": "3–10m",   "anchor": "vehicle scale (car/armoured car/small boat/room)"},
    {"id": "F", "range": ">10m",    "anchor": "building/ship/aircraft scale"},
]

DRAFT_FORMS = [
    {"id": "faceted",    "judge": "clear creases and flat-panel assembly (armour/military kit/mechanical plates)",
     "impl": "primitives + boolean → bevel (2–3 segments to keep hard edges) → audit_mesh"},
    {"id": "smooth",     "judge": "continuous large curvature but still an engineered body (sheet metal/consumer electronics/rounded prop)",
     "impl": "Bevel(2) → SubSurf(2) or crease_lines(radius_mm=…) (radius only arrives at S3)"},
    {"id": "organic",    "judge": "no creases, strong volume, biological form",
     "impl": "sculpt_setup(VOXEL) → sculpt_apply(displacement brush); do not pile up volume with booleans"},
    {"id": "rotational", "judge": "obtained by revolving around one axis (bottle/can/hub/nozzle/flash hider)",
     "impl": "shape_revolve (profile revolved around the axis) — do not loft"},
    {"id": "plate",      "judge": "long in one dimension, section essentially constant (plate/tube/airfoil/receiver)",
     "impl": "section_outline/superellipse + feature lines → shape_loft"},
    {"id": "repeats",    "judge": "regular arrangement of identical parts (tracks/cooling fins/teeth/rivets)",
     "impl": "generator_save→run (change parameters, not code) or Array+Curve"},
    {"id": "sweep",      "judge": "slender parts that follow a path (pipes/cables/rails/railings)",
     "impl": "sweep_analyze (bend radius first) → sweep_build"},
]

DRAFT_FEATURES = [
    {"id": "void_through", "judge": "you can see the background through it", "attrs": ["through/blind", "position (part + upper/middle/lower)", "order of magnitude 1|a few|array"],
     "impl": "boolean (judge with destructive_guard first) or shape it directly by lofting"},
    {"id": "boss",         "judge": "local outward bulge",     "attrs": ["shape block|column|rib", "position", "aspect-ratio class"],
     "impl": "primitives + union + bevel"},
    {"id": "recess",       "judge": "local inward recess",     "attrs": ["opening shape", "position", "whether it is a slot"],
     "impl": "boolean difference / inset_lines (inset_mm only arrives at S3)"},
    {"id": "seam",         "judge": "seam/line between two parts",   "attrs": ["direction longitudinal|transverse|circumferential", "whether it passes through"],
     "impl": "shape_panels produces real seams → clear_check (seam width is only measured at S5)"},
    {"id": "thin_wall",    "judge": "a plate-like structure",      "attrs": ["position", "whether 3D printing is needed"],
     "impl": "loft/extrude into a plate; wall thickness goes through print_report (**measured only at S5**)"},
    {"id": "grille",       "judge": "periodic hole array/grille",   "attrs": ["row/column order of magnitude", "orientation"],
     "impl": "generator_* or Array + batch boolean"},
]

DRAFT_ROLES = ["main", "accessory", "repeated"]

DRAFT_RULES = [
    {"id": "R1", "rule": "do not measure exact dimensions", "check": "a dimension field may only be a size class A–F or a relative ratio (e.g. 0.3×); an absolute mm/cm value is rejected"},
    {"id": "R2", "rule": "do not count meshes",   "check": "calling audit_scene / audit_mesh / print_report (object count·face count·vertex count) is forbidden at this stage; only magnitude estimates such as part_count_hint are allowed"},
    {"id": "R3", "rule": "do not nail data down",   "check": "every field carries confidence(high|mid|low) and source; write unknown when undecidable; every part must carry to_confirm (drives refinement once the images arrive)"},
]

DRAFT_FORBIDDEN_OPS = ["audit_scene", "audit_mesh", "print_report", "print_walls", "print_overhang",
                       "shape_sections", "vehicle_sections", "img_rectify", "vehicle_package"]

DRAFT_ITERATION = [
    "S0 draft (no images, this step): T1 in full + T2 skeleton + qualitative T3/T4; fidelity=draft, everything provisional",
    "S1 reading images: img_scan only gives bbox/aspect ratio/main-axis angle — pixels ≠ millimetres, still no mm",
    "S2 calibration (the first numbers): img_rectify → mm_per_px → envelope, provisional turning into confirmed step by step",
    "S3 station table/section: shape_sections + the section_path shape_plan gives (mm only allowed here)",
    "S4 image comparison: shape_loft → qc_render_views(ref_path=) per-view IoU + feature-line comparison",
    "S5 acceptance: audit_* / gate_run (only here do we count faces and measure clearances)",
]

_DRAFT_T1 = [
    {"k": "name", "ask": "what this thing is", "how": "read the requirement text / name it straight from the image", "precision": "qualitative", "refine": "basically unchanged"},
    {"k": "class", "ask": "which class it belongs to", "how": "map onto one of shape_plan's 10 classes; 1 primary + 1 alternative allowed", "precision": "coarse classification", "refine": "review section_path once the images arrive"},
    {"k": "size_class", "ask": "roughly how big in reality", "how": "log-scale class A–F + human-scale anchor (pocket/one-handed/in the arms/one person tall/car length/building)", "precision": "class only, mm forbidden", "refine": "mm only after S2 calibration"},
    {"k": "size_ref", "ask": "what to use as a reference", "how": "human-scale anchor, no numbers", "precision": "qualitative anchor", "refine": "replace with the measured envelope"},
    {"k": "symmetry", "ask": "symmetry", "how": "bilateral / axisymmetric / single-sided chirality / none", "precision": "qualitative", "refine": "review"},
    {"k": "orientation", "ask": "axis semantics", "how": "long axis·width axis·thin axis + which one points up/forward (state the project coordinates, e.g. +X=muzzle)", "precision": "qualitative", "refine": "freeze into the spec"},
    {"k": "confidence", "ask": "how sure", "how": "high/mid/low", "precision": "—", "refine": "raise round by round"},
]

_DRAFT_T2 = [
    {"k": "part", "ask": "what this block is called", "how": "semantic naming (Cube.001 and the like are forbidden)", "precision": "qualitative", "refine": "reuse it as the object name"},
    {"k": "role", "ask": "main part or accessory", "how": "criteria (qualitative, no volume maths): ① holds the main share of the envelope volume ② two or more parts attach to it ③ without it the whole does not hold up — meet ① and it is main, the rest are accessory/repeated", "precision": "exactly one main (several may tie for multiple volumes), editable", "refine": "review after assembly"},
    {"k": "parent", "ask": "what it hangs off", "how": "assembly tree (main is the root)", "precision": "coarse, editable", "refine": "interface table (spec)"},
    {"k": "size_class", "ask": "size class of this part", "how": "the same A–F classes as T1", "precision": "class", "refine": "S2 calibration"},
    {"k": "rel", "ask": "ratio relative to the main part", "how": "eyeballed ratio, e.g. 1.0× / 0.3× (mark approx)", "precision": "coarse", "refine": "correct against measurements"},
    {"k": "form_class", "ask": "what shape", "how": "see T3 (one object is often a mixture: label part by part)", "precision": "qualitative", "refine": "pick the section path at S3"},
    {"k": "features", "ask": "which spatial features it has", "how": "see T4; record only through/blind, position class, order of magnitude", "precision": "qualitative", "refine": "give dimensions at S3"},
    {"k": "build_path", "ask": "how to build it", "how": "fill in the operator chain: the section_path shape_plan(object_class=…) gives + the skill recipe (see impl in T3)", "precision": "coarse route, editable", "refine": "freeze into the spec"},
    {"k": "evidence", "ask": "on what basis", "how": "state the source: requirement text / reference image N / common-sense prior", "precision": "required, may not be empty", "refine": "add the image number once the images arrive"},
    {"k": "to_confirm", "ask": "what the images must settle", "how": "e.g. section shape / how many times that feature appears / whether there is a second one of the same kind", "precision": "required (this column drives the iteration)", "refine": "close out item by item"},
    {"k": "confidence", "ask": "how sure", "how": "high/mid/low", "precision": "—", "refine": "raise round by round"},
]


def _draft_record_skeleton(object_class=None):
    return {
        "object": {"name": None, "class": (object_class or None), "size_class": None, "size_ref": None,
                   "symmetry": None, "orientation": None, "confidence": None, "source": None},
        "parts": [{"part": None, "role": None, "parent": None, "size_class": None, "rel": None,
                   "form_class": None, "features": [], "build_path": None,
                   "evidence": None, "to_confirm": [], "confidence": None}],
        "part_count_hint": None,
    }


def shape_draft(object_class=None, hint=None):
    """S0 draft assessment: the field contract for the "production table" + a fillable skeleton. **This op returns no measured values.**

    object_class is optional (one of vehicle/humanoid/…) — when given it also carries that class's "focus items" (which ratios to watch,
    which section path is suggested), but **only the names of the focus items, without numbers**; values are always taken after S2 calibration.
    """
    c = str(object_class).lower() if object_class else None
    focus = None
    unknown_class = None
    if c:
        if c in CLASSES:
            row = CLASSES[c]
            focus = {"object_class": c, "views": row.get("views"), "symmetric": row.get("symmetric"),
                     "volumes": row.get("volumes"), "focus_ratios": row.get("ratios"),
                     "section_path": SECTION_PATH.get(c), "traps": row.get("traps"),
                     "note": "the above are **the names of the focus items** (what to watch), not measurements; values are taken after S2 calibration"}
        else:
            unknown_class = {"object_class": object_class, "known": sorted(CLASSES)}
    out = {
        "ok": True, "op": "shape_draft", "stage": DRAFT_STAGE, "fidelity": "draft", "revisable": True,
        "what": "the **first step** of reference-image reconstruction: produce a production table first (what it is/how big roughly/how many blocks/what shape each is/where it bulges or recesses),"
                "like drafting it in your head — **do not nail the data down**, fill the numbers in row by row once the images arrive",
        "why_draft": "at this stage there is usually no reference image yet; measuring mm / counting meshes first means treating invented numbers as the spec, and it all gets thrown away when the images arrive",
        "rules": DRAFT_RULES,
        "forbidden_ops_this_stage": DRAFT_FORBIDDEN_OPS,
        "forbidden_note": "**do not call** the operators above at stage S0 (they produce exact dimensions or object/face statistics); use them only at S3/S5",
        "enums": {"size_class": SIZE_CLASSES, "form_class": DRAFT_FORMS, "feature_kind": DRAFT_FEATURES,
                  "role": DRAFT_ROLES, "confidence": ["high", "mid", "low"]},
        "tables": {
            "T1_object": {"one_row": True, "fields": _DRAFT_T1,
                          "done_when": "name + class + size_class all present = T1 done (no mm number required)"},
            "T2_parts": {"one_row_per_part": True, "fields": _DRAFT_T2,
                         "done_when": "every part has role/form_class/evidence/to_confirm = T2 done;"
                                      "this table is also the seed of the later work split and interface table"},
            "T3_form": {"one_row_per_part": True, "enums": DRAFT_FORMS,
                        "rule": "one object is often a mixture (e.g. a character = organic body + hard-surface gear) ⇒ label part by part, one overall answer is not required"},
            "T4_features": {"one_row_per_feature": True, "enums": DRAFT_FEATURES,
                            "rule": "locate only down to 'part + upper/middle/lower, front/back' and order of magnitude; hole diameter/depth/wall thickness wait for S3/S5"},
        },
        "record": _draft_record_skeleton(c if (c and c in CLASSES) else None),
        "iteration": DRAFT_ITERATION,
        "next": "① fill record into the table → shape_draft_check(record=…) for mechanical validation;"
                "② once the reference image arrives → S1 img_scan (outline/ratios only, no mm) → S2 img_rectify calibration",
    }
    if focus:
        out["focus"] = focus
    if unknown_class:
        out["unknown_class"] = unknown_class
        out["warning"] = "unknown object_class=%s — the generic focus items still apply (measure the three envelope ratios length/width/height first)" % object_class
    if hint:
        out["hint_echo"] = str(hint)[:200]

    return _j(out)


def _draft_scan_absolute(obj, path="", hits=None):
    """Recursively find absolute mm/cm values (keys ending in _mm/_cm, or strings carrying a number + unit)."""
    if hits is None:
        hits = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            kp = path + "." + str(k)
            lk = str(k).lower()
            if lk.endswith("_mm") or lk.endswith("_cm") or lk in ("mm", "cm"):
                hits.append(kp)
            _draft_scan_absolute(v, kp, hits)
    elif isinstance(obj, (list, tuple)):
        for i, v in enumerate(obj):
            _draft_scan_absolute(v, "%s[%d]" % (path, i), hits)
    elif isinstance(obj, str):
        if _DRAFT_MM_RE.search(obj):
            hits.append("%s = %s" % (path, obj[:48]))
    return hits


def shape_draft_check(record=None):
    """Validate the S0 draft table: are the fields complete + any violations (mm-level dimensions / face-count statistics).

    record may be a dict or a JSON string (same shape as the record skeleton returned by shape_draft).
    Returns errors (must fix) / warnings (worth a look); **does not modify the scene**.
    """
    if isinstance(record, str):
        try:
            record = json.loads(record)
        except Exception as e:
            return _j({"ok": False, "stage": DRAFT_STAGE, "error": "record is not valid JSON: %s" % str(e)[:160]})
    if record is None:
        return _j({"ok": False, "stage": DRAFT_STAGE,
                   "error": "record is missing — call shape_draft() for the skeleton first, fill it in, then pass record={object:…, parts:[…]}"})
    if not isinstance(record, dict):
        return _j({"ok": False, "stage": DRAFT_STAGE, "error": "record must be an object (dict)"})

    errors, warnings = [], []
    valid_size = {x["id"] for x in SIZE_CLASSES}
    valid_form = {x["id"] for x in DRAFT_FORMS}
    valid_feat = {x["id"] for x in DRAFT_FEATURES}
    valid_conf = {"high", "mid", "low"}

    obj = record.get("object")
    if not isinstance(obj, dict):
        errors.append("missing object section (T1)")
        obj = {}
    for k in ("name", "class", "size_class", "size_ref", "confidence"):
        if not obj.get(k):
            errors.append("object.%s is missing (T1 incomplete)" % k)
    if obj.get("class") and str(obj["class"]).lower() not in CLASSES:
        errors.append("object.class=%s is not one of shape_plan's 10 classes (%s)" % (obj["class"], ",".join(sorted(CLASSES))))
    if obj.get("size_class") and str(obj["size_class"]).upper() not in valid_size:
        errors.append("object.size_class=%s is not an A–F class (size_class only accepts a class, not a number)" % obj["size_class"])
    if obj.get("confidence") and str(obj["confidence"]).lower() not in valid_conf:
        errors.append("object.confidence=%s is not high/mid/low" % obj["confidence"])

    parts = record.get("parts")
    if not isinstance(parts, list) or not parts:
        errors.append("parts is empty (T2 needs at least one row, and the main part counts as one)")
        parts = []
    n_main = 0
    for i, p in enumerate(parts):
        tag = "parts[%d]" % i
        if not isinstance(p, dict):
            errors.append("%s is not an object" % tag)
            continue
        pname = str(p.get("part") or "").strip()
        if not pname:
            errors.append("%s.part is missing (it has to be named first)" % tag)
        elif _DRAFT_AUTO_RE.match(pname):
            warnings.append("%s.part=%s looks like an automatic name, use a semantic name" % (tag, pname))
        for k in ("role", "form_class", "evidence", "to_confirm", "confidence"):
            v = p.get(k)
            if v is None or (isinstance(v, str) and not v.strip()) or (isinstance(v, list) and not v):
                errors.append("%s.%s is missing (every T2 part needs role/form_class/evidence/to_confirm/confidence)" % (tag, k))
        role = str(p.get("role") or "")
        if role and role not in DRAFT_ROLES:
            errors.append("%s.role=%s is not one of %s" % (tag, role, "/".join(DRAFT_ROLES)))
        if role == "main":
            n_main += 1
        fc = str(p.get("form_class") or "")
        if fc and fc not in valid_form:
            errors.append("%s.form_class=%s is not in %s" % (tag, fc, ",".join(sorted(valid_form))))
        if str(p.get("confidence") or "").lower() not in valid_conf and p.get("confidence"):
            errors.append("%s.confidence=%s is not high/mid/low" % (tag, p["confidence"]))
        feats = p.get("features")
        if isinstance(feats, list):
            for j, f in enumerate(feats):
                if not isinstance(f, dict):
                    errors.append("%s.features[%d] is not an object" % (tag, j))
                    continue
                fk = str(f.get("kind") or "")
                if fk and fk not in valid_feat:
                    errors.append("%s.features[%d].kind=%s is not in %s" % (tag, j, fk, ",".join(sorted(valid_feat))))
                if not f.get("where"):
                    warnings.append("%s.features[%d] has no where (position) — at least write the part + upper/middle/lower" % (tag, j))
    if n_main == 0:
        warnings.append("no part is marked role=main — decision rule: the part holding the main share of the envelope volume is the main one")
    if n_main > 1:
        warnings.append("%d parts are marked main — multiple volumes may tie, but confirm they are not blocks of one and the same part" % n_main)

    mm_hits = _draft_scan_absolute(record)
    if mm_hits:
        errors.append("R1 violation: absolute mm/cm values appear %s — S0 only accepts the size classes A–F or relative ratios (e.g. 0.3×)"
                      % (", ".join(sorted(set(mm_hits))[:6])))

    stats = {"parts": len(parts), "main": n_main,
             "forms": sorted({str(p.get("form_class")) for p in parts if isinstance(p, dict) and p.get("form_class")}),
             "feature_rows": sum(len(p.get("features") or []) for p in parts if isinstance(p, dict))}
    return _j({"ok": not errors, "stage": DRAFT_STAGE, "fidelity": "draft",
               "errors": errors, "warnings": warnings, "stats": stats,
               "note": "ok=true means 'the draft table is filled in acceptably and the data is not nailed down'; **it does not mean the dimensions were verified** — "
                       "numbers always wait for S2 calibration/S5 acceptance"})


def shape_selftest():
    """Self-test: the protocol is complete (every class has views/ratios/operators/acceptance/traps) + the three paths (measuring tool/loft/rotational body) work."""
    import bpy
    ev = {}
    try:
        missing = []
        for k, row in CLASSES.items():
            for key in ("views", "ratios", "ops", "gates", "traps"):
                if not row.get(key):
                    missing.append("%s.%s" % (k, key))
        missing_path = [k for k in CLASSES if not SECTION_PATH.get(k)]
        ev["classes"] = len(CLASSES)
        ev["missing_section_path"] = missing_path
        ev["decision_rules"] = len(DECISION)
        ev["missing_fields"] = missing
        p = json.loads(shape_plan("generic"))
        ev["plan_generic"] = {"ok": p.get("ok"), "steps": len(p.get("steps") or [])}
        rv = json.loads(shape_revolve(profile=[[0, 0], [30, 0], [30, 60], [20, 90], [0, 100]], name="__dsh_rv"))
        ev["revolve"] = {k: rv.get(k) for k in ("ok", "size_mm", "vertices", "error")}
        # S0 draft contract: templates must be complete (four tables + rules + forbidden ops), and check must "pass a legal one / reject mm"
        dr = json.loads(shape_draft("furniture"))
        good = {"object": {"name": "sample", "class": "furniture", "size_class": "C",
                           "size_ref": "held in the arms", "confidence": "mid"},
                "parts": [{"part": "seat surface", "role": "main", "form_class": "plate", "evidence": "requirement text",
                           "to_confirm": ["seat surface shape"], "confidence": "mid"}]}
        bad = {"object": dict(good["object"]), "parts": [dict(good["parts"][0], rel="450mm")]}
        ck_ok = json.loads(shape_draft_check(good))
        ck_bad = json.loads(shape_draft_check(bad))
        ev["draft"] = {"ok": dr.get("ok"), "tables": sorted((dr.get("tables") or {}).keys()),
                       "rules": len(dr.get("rules") or []),
                       "forbidden": len(dr.get("forbidden_ops_this_stage") or []),
                       "check_good": ck_ok.get("ok"), "check_mm_rejected": ck_bad.get("ok") is False}
        ok = (not missing and not missing_path and len(DECISION) >= 4
              and p.get("ok") is True and rv.get("ok") is True
              and abs((rv.get("size_mm") or {}).get("h", 0) - 100.0) < 1.0
              and dr.get("ok") is True and len(dr.get("tables") or {}) == 4
              and ck_ok.get("ok") is True and ck_bad.get("ok") is False)
        return _j({"ok": bool(ok), "evidence": ev})
    except Exception as e:
        return _j({"ok": False, "evidence": ev, "error": "%s: %s" % (type(e).__name__, str(e)[:220])})
    finally:
        o = bpy.data.objects.get("__dsh_rv")
        if o is not None:
            me = o.data
            bpy.data.objects.remove(o, do_unlink=True)
            if me is not None and me.users == 0:
                try:
                    bpy.data.meshes.remove(me, do_unlink=True)
                except Exception:
                    pass


def shape_help():
    return _j({
        "module": "shapegen.py", "version": SHAPE_VERSION,
        "what": "**generic** reference-image reconstruction method layer: class protocols + generic measuring/lofting/fitting/part-splitting/rotational body",
        "ops": ["shape_draft", "shape_draft_check", "shape_plan", "shape_sections", "shape_loft",
                "shape_fit", "shape_regions", "shape_panels", "shape_revolve", "shape_selftest", "shape_help"],
        "steps": STEPS, "classes": sorted(CLASSES),
        "section_decision": DECISION, "section_path": SECTION_PATH,
        "why": "the geometry mechanism is independent of class: measure the outline → loft → feature lines → acceptance; switching class only switches the protocol (views/ratios/acceptance)",
        "draft_stage": "the first step is always the S0 draft assessment (shape_draft): produce the production table first, **do not measure exact dimensions, do not count meshes, do not hardcode numbers**;"
                       "dimensions only as A–F size classes, every part must carry evidence and to_confirm — fill the numbers in row by row once the images arrive",
        "applies_to": ["objects with a clear outer silhouette that can be described with orthographic views: vehicle/humanoid/animal/furniture/helmet/hull/aircraft/firearm/prop"],
        "not_applies": ["things without an outer silhouette (cloth/fur/fluid/smoke)", "things defined by internal structure (porous lattice/topology-optimised part)"],
        "rotational_note": "**axisymmetric** objects such as bottle/can/hub/vase go through shape_revolve (profile revolved), do not loft",
    })


def shape_dispatch(op, args_json):
    args = {}
    if isinstance(args_json, str) and args_json.strip():
        try:
            args = json.loads(args_json)
        except Exception as e:
            return _j({"ok": False, "error": "args is not valid JSON: %s" % str(e)[:120]})
    kw = {}
    for k, v in (args or {}).items():
        if k == "args" and isinstance(v, dict):
            kw.update(v)
        else:
            kw[k] = v
    ops = {"plan": shape_plan, "sections": shape_sections, "loft": shape_loft, "fit": shape_fit,
           "regions": shape_regions, "panels": shape_panels, "revolve": shape_revolve,
           "draft": shape_draft, "draft_check": shape_draft_check,
           "selftest": shape_selftest, "help": shape_help}
    fn = ops.get(str(op))
    if fn is None:
        return _j({"ok": False, "error": "unknown shape op", "op": op, "ops": sorted(ops)})
    try:
        return fn(**kw)
    except Exception as e:
        return _j({"ok": False, "error": "%s: %s" % (type(e).__name__, str(e)[:220]), "op": op})


_DshApi = _KIT.Api  # shared kernel (the trailing registration line needs no change)
import sys as _sys
_K = _sys.modules.get("dsh_rt_kernel")
if _K is not None:
    _K.dsh_shape_api = _DshApi({"version": SHAPE_VERSION, "dispatch": shape_dispatch,
                                "draft": shape_draft, "draft_check": shape_draft_check,
                                "plan": shape_plan, "sections": shape_sections, "loft": shape_loft,
                                "fit": shape_fit, "revolve": shape_revolve, "selftest": shape_selftest,
                                "help": shape_help})