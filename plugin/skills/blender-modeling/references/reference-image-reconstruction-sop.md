# General Reference Image Reconstruction SOP (independent of object class)

> Companion: plugin `img_*` measuring tools (img_digest/probe/measure/calib) + `shapesolve_*` (silhouette back-solving) + `shape_*`/`vehicle_*` (geometry) + `visualreport_report` (same-camera acceptance).
> In one sentence: **the geometric mechanism is independent of class** — measure first (no mm without calibration) → loft/back-solve → feature lines → same-camera acceptance; switching class only switches the protocol (views/ratios/acceptance gates).
> Architecture first: prefer plan ops; only write bpy when there is no corresponding capability, and you must still pass the plugin gate for acceptance.

## 0. When it applies and when it does not

| | Object |
|---|---|
| **Applicable** | Objects with a clear outer silhouette that can be described with orthographic views: vehicles / humanoids / animals / furniture / helmets / hulls / aircraft / firearms / props |
| **Needs a variant** | Axisymmetric (→ `shape_revolve`) / multi-volume (→ `shape_regions`) / only half modeled (symmetric parts) / flexible but shaped (seat cushion) |
| **Not applicable** | Objects without an outer silhouette (cloth / hair / fluids / smoke) / objects defined by internal structure (porous lattices / topology-optimized parts) |

## 1. Nine steps (S0 draft → every step has numbers)

> **Step ⓪ is a draft, not a spec**: this step **does not measure exact dimensions, does not count meshes, does not lock numbers down**. It answers only six things:
> what it is / roughly how big (magnitude band only) / how many pieces it splits into / which piece is the main body and which are attachments / which part is hard-surface and which is surface / where the cut-outs, protrusions and recesses are.
> Only after the reference image arrives do you start from step ① filling the draft **line by line** with numbers; the rough numbers in the draft are **not inherited** as spec.

| Step | Action | Operator | Output/criterion |
|---|---|---|---|
| ⓪ | **Draft assessment** (draft in your head) | `shape_draft` → fill `record` → `shape_draft_check` | **Production tables** (T1 identification and magnitude / T2 production units / T3 form / T4 spatial features); criterion = `shape_draft_check` `ok=true` (no mm-level absolute values, no empty fields). **`audit_*` / `print_report` must not be called in this step, and no mm is produced** |
| ① | Rectify | `img_rectify` (four-corner homography, pure numpy) | Orthographic image + `mm_per_px`; **mandatory for photos**, but only valid for "the plane the points were picked on" (see §3.1) |
| ② | Measure the envelope | First look at `shape_plan(object_class=…)` for that class's key ratios | Length/width/height + class ratios; **do not go any further if the ratio gate fails** |
| ③ | Measure the station table | `shape_sections` (side view per-column top/bottom bounds + top view half-width + front view section outline) | `stations[]` + `section_shape[]` + `package` |
| ④ | Loft | `shape_loft` | Station table sets the silhouette, section outline sets the character |
| ⑤ | Feature lines | `crease_lines` (hard crease lines / `radius_mm` true fillets) + `inset_lines` (grooves on faceted surfaces) | Parameterized surface feel |
| ⑥ | Parameterization (optional) | `shape_fit` (crease-line family + K sweep) | Spec with editable numbers; **IoU for shapes outside the family stalls at ~0.82** |
| ⑦ | Multi-volume/seams | `shape_regions` / `shape_panels` | One volume per piece; seams are real geometry (measurable with `clear_check`) |
| ⑧ | Acceptance | `qc_render_views(ortho, ref_path)` / `img_diff` + `clear_check` + `audit_mesh` | **IoU per view** + dimension/ratio/clearance numbers (IoU judges the silhouette only, see §4) |

### 1.1 The four tables of step ⓪ (`shape_draft` provides the field contract directly)

`shape_draft(object_class=…)` returns a fillable skeleton + field definitions for the four tables; once filled, `shape_draft_check(record=…)` validates it mechanically.

| Table | What it judges | How it is done (basis / tool) | Draft-stage precision |
|---|---|---|---|
| **T1 Identification and magnitude** | What it is / which class it falls into / roughly how big / symmetry and axes | Name it directly → map to the 10 classes of `shape_plan`; dimensions use **logarithmic bands A–F** (<10cm / 10–30cm / 0.3–1m / 1–3m / 3–10m / >10m) + human-scale anchors (palm-sized / one-handed / armful / one person tall / car-length / building) | Band only, **no mm** |
| **T2 Production units** (core) | Which pieces exist, which is the main body and which are attachments | Semantic naming → `role`: ① occupies the main volume of the envelope ② two or more pieces attach to it ③ without it the whole does not hold together — **satisfying ① makes it the main body**; the rest are attachments/repeats → `parent` assembly tree → `build_path` (`section_path` from `shape_plan` + skill recipe) | Main body unique (multi-volume may be parallel), changeable |
| **T3 Form** | Hard-surface or surface | 7 qualitative criteria: `faceted` (edges + planar assembly) / `smooth` (continuously curved engineering body) / `organic` / `rotational` / `plate` / `repeats` / `sweep`. **Hybrids are marked per piece** (character = organic body + hard-surface gear) | Judges the surface feel only, not radii/segment counts |
| **T4 Spatial features** | Cut-outs / protrusions / recesses / seams / thin walls / grilles | One row each: `kind` + `where` (part + top/middle/bottom or front/back) + order of magnitude (1 / several / array); cut-outs marked through/blind | Does not compute hole diameter, depth or wall thickness |

**The three hard rules of S0** (`shape_draft_check` mechanically enforces the first two):

1. **R1 Do not measure exact dimensions** — dimension fields may only be magnitude bands or relative ratios (e.g. `0.3×`); any mm/cm-level absolute value is rejected.
2. **R2 Do not count meshes** — `audit_scene` / `audit_mesh` / `print_report` are forbidden; only order-of-magnitude estimates such as `part_count_hint` are allowed.
3. **R3 Do not lock data down** — every field carries `confidence`(high/mid/low) and `source`; if undecidable, write `unknown`; **every piece must carry `to_confirm`** (this column is the punch list of "what to fill in once the image arrives").

> Why R3 is called out separately: the most expensive mistake at the draft stage is not judging wrong, but **writing something misjudged into the spec** — everyone downstream then models to the wrong numbers, and rework costs the whole thing.

## 1.5 Three extensions (added 2026-09-26)

| Need | What to use | Notes |
|---|---|---|
| **Airfoil / cambered / left-right asymmetric section** | `vehicle_loft(section_outline=[[y_mm,z_mm],…])` | Explicit closed outline normalized per station (y by half-width, z by station height); `section_source=custom_outline`. The front-view per-row width path is **necessarily left-right symmetric**, so airfoils must take this one |
| **Rotational body + multi-volume assembly** (wheel hub + tire, bottle body + cap, nozzle array) | `shape_revolve(parts=[{profile, at:[x,y,z]_mm, name}])` | Each piece is its own object + its own placement; after assembly verify clearance with `clear_check` as usual |
| **Square/concave control of fillets (G2 approximation)** | Add `profile` to a `crease_lines` entry | 0.5 = true round; >0.5 more square (closer to a smooth G2 transition); <0.5 more concave. Receipt `bevel.profile` |

### Which section path to choose (decision rules, returned by `shape_plan` with the protocol)

1. **Axisymmetric** (bottle/can/hub/vase/nozzle) => `shape_revolve` — **do not** use loft
2. **Left-right symmetric + front view has a silhouette** => `section_shape` (normalized per-row width, scaled by station half-width)
3. **Cambered / left-right asymmetric / needs precise section control** (airfoils, receivers, shaped parts) => `section_outline` (explicit closed outline)
4. **Only one side silhouette, section essentially constant along the length** (plates, profiles) => superellipse `section_pts` + feature lines is enough
5. **Multi-volume** => `shape_regions` / `shape_revolve(parts=[...])`, verify clearance with `clear_check` after assembly

> The `section_path` for each class is given directly by `shape_plan(object_class=...)`; no need to go back and dig through the CHANGELOG.

## 2. Class protocols (given directly by `shape_plan`)

| Class | Views | Key ratios | Primary operators | Main pitfalls |
|---|---|---|---|---|
| vehicle | s f t | WBR / wheelbase ratio / height-to-length ratio / track ratio / front and rear overhang | `vehicle_package` `vehicle_loft` `clear_check` | Wheel diameter cannot be back-solved from the silhouette; without a top view the body comes out too narrow |
| humanoid | s f | head-to-body ratio 7–8 / shoulder width ≈ 1.5 head heights | `human_base` `human_head` `motion_joints` | A photoreal face is not achievable → cover it with a mask |
| creature | s f t | body length/shoulder height / head length/body length | `shape_loft` | Quadruped ≠ biped proportions; hair does not apply |
| headwear | s f t | head height:width:depth ≈ 233:175:206; eye line 0.50 / nose base 0.725 / mouth line 0.825 | `human_head` `face_ratios` | Leave head-circumference clearance in the inner cavity |
| furniture | s f | seat height/seat depth/backrest angle | `shape_regions` `sweep_build` | Ergonomics takes priority over shape similarity |
| hull | s t | length/beam/depth | `shape_loft` | **Station tables must be given separately above and below the waterline** |
| aircraft | s f t | wingspan/fuselage length / chord distribution | `shape_regions` `sweep_build` | Wings use an **airfoil section**, not a superellipse |
| rotational | s (single profile) | height/diameter / position of the maximum diameter | `shape_revolve` | **do not use loft** |
| weapon | s t | overall length / grip position | `shape_regions` `clear_check` | Grip dimensions are a hard constraint |
| generic | s f (+t) | measure the three envelope ratios first | `shape_sections` `shape_loft` `img_diff` | rectify photos first |

## 3. Three decisive details (all learned the hard way in practice)

1. **Without a top view there is no plan-view taper**: with only side + front views `half_w_mm` is missing and the car body narrows to 460mm (should be 1850mm); now "front-view maximum width × taper assumption" is used to backfill, and the assumption source is noted in the receipt.
2. **Wheel diameter / ground contact body cannot be back-solved from a filled silhouette** (wheel and body merge into one); but **axle position can** (clustering the low-dip segments at the bottom of the silhouette).
3. **Feature lines cannot be matched to edges by z band** (vertices are discrete around the ring, the target height often has no edge → 0 hits); use **ring indices**; transverse feature lines additionally need **automatic station insertion**.

### 3.1 The capability boundary of `img_rectify`: a homography corrects only one plane (★)

A four-point homography holds exactly for points that **lie precisely on the physical plane the points were picked on**; for points off that plane the error grows rapidly with depth.
Measured in practice (homography fitted on the z=0 plane; at that camera position 1 m ≈ 190 px):

| Distance of the point from the z=0 plane | Maximum error | Converted |
|---|---|---|
| 0 m | **0.000 px** | 0 mm |
| 0.05 m | 9.906 px | **52 mm** |
| 0.20 m | 40.194 px | **211 mm** |
| 0.50 m | 103.464 px | **543 mm** |

⇒ **Planar references** (photographed drawings / calibration boards / flat-laid stickers / ground calibration frames) are fully correct;
**solid objects** (cars / people / buildings / helmets) are only accurate on the plane the points were picked on — the wheel-arch flare, fender curvature, A-pillar rake and
nose-cone depth that lie **far from that plane** all measure wrong. Either measure only dimensions close to that plane,
or switch to real camera calibration (intrinsics + extrinsics, multi-view geometry), **not** a homography.

### 3.2 Cross-depth error is not ±5%

Under perspective, scale varies with depth as `1/z`, and the error bound is computable: `err ≈ Δz / (D + Δz)` (`D` = distance from the camera to the near scale reference, `Δz` = depth difference).
Measured in practice (D = 8 m): `Δz=0.5m → −5.88%`; `Δz=1m → −11.1%`; `Δz=3m → −27.3%` — matching the analytical formula line by line.
⇒ **a depth span of just 0.5 m already exceeds ±5%**. If `D` / `Δz` cannot be estimated, record `unresolved`; do not write "±5% should be enough".

## 4. Acceptance discipline

- **Numeric gates run themselves** (`audit_*` / `qc_*` / `clear_check` / `img_diff`): scripted criteria, no model needed; if the receipt is large use `summary_only:true` / `top_k:N`.
- **Only subjective items** ("is this surface feel right") need a fresh perspective; give it `references/acceptance-checklist.md`, not the whole SKILL.md.
- **Compute IoU separately for each view**: the side view most easily reaches 0.9+ first, the top view is hardest (plan-view taper depends entirely on it).
- ★ **IoU is only "silhouette overlap under that view"**; it is a **necessary but not sufficient** condition. It **cannot see**: depth/thickness, internal features
  (panel gaps/grilles/lights/masks/feature-line positions), surface tension (surface feel), other views, volume distribution. And "filling the silhouette" alone can inflate it.
  ⇒ meeting the IoU **only disproves "the silhouette is wrong"**; it cannot prove "it looks alike"; it must be paired with `clear_check` clearances + `audit_measure` dimensions + feature-line comparison.
  **Do not chase `target_iou` as a delivery target.**
- **If IoU cannot be reached, look back at which layer is wrong**: envelope wrong (ratio gate fails) → fix the envelope; silhouette wrong (side-view IoU low) → fix the station table; surface feel wrong (IoU high but it looks wrong) → fix feature lines/fillets.

## 5. Iteration discipline from draft → numbers (S0 → S5)

| Stage | Allowed output | Forbidden |
|---|---|---|
| **S0 draft** (no image) | Category, magnitude band A–F, part breakdown, main body/attachments, qualitative form and space | Any mm; object/face counts; writing numbers into the spec |
| S1 read the image | `img_digest`'s bbox / aspect ratio / principal axis angle / holes / readability; `img_probe` local measurements | Treating pixels as millimetres (pixels ≠ mm) |
| S2 calibration | `img_measure` (known edge length/two points) or `img_calib` (multi-view) → `px_per_mm` → envelope in mm (**first appearance of numbers**) | Using S0's rough bands as measured values; writing mm without calibration |
| S3 station table/sections | `shape_sections` + the `section_path` from `shape_plan` (mm is free at this point) | Skipping ①②③ and lofting directly |
| S4 render comparison | `qc_render_views(ref_path=)` per-view IoU + feature-line comparison | Using single-view IoU as proof of "looks alike" |
| S5 acceptance | `audit_*` / `gate_run` (**only at this step** count faces, measure clearances) | Treating `degraded` as pass |

**Field upgrades must leave a trace**: whenever a value goes from `provisional` to `confirmed`, record "which image / which receipt confirmed it";
S0's bands are used only for **routing** (choosing the section path, choosing the recipe, deciding the division of work), **not for filling the spec** — this is the operational meaning of "do not lock things down in the draft".

