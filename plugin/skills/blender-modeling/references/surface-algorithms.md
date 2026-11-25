# Surface Algorithm Reference (surface_*)

Parametric surfaces in pure bpy + numpy: spec → mesh → QC → GLB. No dependency on OCCT / geomdl / trimesh, ships with the plugin, runs both in the GUI and headless.

## 1. When to use

- Section loft: bottle bodies, cowlings, fuselage segments, roof transitions → surface_loft
- Sweep along a path: tubes, beams, skirts, cable routing → surface_sweep
- Four-sided patch: Class-A transitions, local surfaces → surface_patch
- Turn an existing spec into a mesh → surface_tessellate
- Mesh checkup (continuity/curvature/self-intersection/thickness) → surface_validate
- Export GLB for external viewing/delivery → surface_export

Primitives/faceted hard-surface work use bmesh/geo+Bevel; organic work uses sculpt_*; if you need G2/CAD offset, do not use this family.

## 2. Ops and key parameters

| op | Key parameters | Notes |
|---|---|---|
| surface_loft | sections=[{z_mm, points_mm:[[x,y]...]}], degree(1..7), continuity(G0/G1/G2), closed, tessellation{u,v} | Interpolating B-spline through the sections; z is linear along v |
| surface_sweep | profile_mm, rail_mm, orientation(auto/up_z/up_y/fixed), twist_deg, scale | Parallel-transport frame + accumulated twist + per-point scale |
| surface_patch | control_grid (regular grid), degree_u/degree_v | Tensor-product clamped B-spline patch |
| surface_tessellate | spec_or_object, quality(draft/normal/fine) | spec→mesh; object→bake the evaluated mesh |
| surface_validate | spec_or_object + continuity/curvature/self_intersection/thickness switches | Returns verdict/metrics/checks/defects/next |
| surface_export | spec_or_object, out_dir, name | Exports GLB; returns path/bytes/tris |
| surface_blend / surface_offset | — | M5 not implemented: explicit ok:false (needs OCCT) |
| surface_fit | — | M3 not implemented: interface reserved |
| surface_selftest / surface_help | No arguments | On-machine self-test / parameter quick reference |

SurfaceSpec fields: `kind`(loft/sweep/patch), `units:"mm"`, `degree`(1..7), `continuity`(G0/G1/G2), `closed`, `constraints{min_thickness_mm, max_curvature_1_per_mm, g1_tol_deg, g2_tol_ratio}` (optional, used by validate), `tessellation{u,v}` (or `quality: draft|normal|fine`).

## 3. Units and reproducibility

- All lengths in mm; internally scaled by scene.unit_settings.scale_length;
- Same spec (including tessellation) ⇒ identical spec_hash, identical vertices (no random numbers, no bpy.ops);
- Object names do not affect spec_hash.

## 4. Three-state verdict

- pass: declared continuity met, no self-intersection, closed-shell thickness met, mesh quality normal;
- fail: confirmed defects (self-intersection/G1 discontinuity/excess curvature/flipped normals/degenerate faces/insufficient thickness);
- degraded: the check did not complete (over max_tris, thickness not measurable) — **degraded does not equal pass**;
- Open-surface thickness is n/a, not fail; defects[] gives check/severity/msg per entry, checks holds the raw numbers for each item, next gives the suggested next step.

## 5. Minimal chain

    surface_loft(sections=[...], degree=2, closed=true, tessellation={u:24,v:8}, name="Cowl")
      → surface_tessellate(spec_or_object=<spec>)        # get the object name
      → surface_validate(spec_or_object=<object>)        # read verdict
      → surface_export(spec_or_object=<object>, out_dir="D:/out", name="Cowl")

## 6. Limitations (honest)

- Between sections it is B-spline interpolation (through the points), but z is linear along v; it is not a NURBS surface;
- Continuity can only be checked along a seamed direction (loft section seam / sweep closing seam); a single patch is n/a;
- Curvature/thickness are discrete approximations, sensitive to tessellation density, and **cannot serve as manufacturing certification**;
- M3 fit is not implemented: there is no solver for back-solving parameters from a reference image; use shapesolve / manual parameters first;
- M5 blend/offset are not implemented (explicit `ok:false`); advanced fillets/offsets need the OCCT backend;
- Lower the density for large meshes first; self-intersection checking over the limit becomes degraded (degraded ≠ pass).

## 7. Working with other tools

- Proportions: img_digest → probe/measure → calib to measure mm first;
- Silhouette: back-solve dimensions with shapesolve_solve, then write the spec;
- Project acceptance: surface_validate is a unit checkup; final acceptance goes through gate_* (three-state);
- Delivery: surface_export produces the GLB; assembly/delivery go through asm_export / deliver_export;
- Visual: qc_render_views / visualreport_report for same-camera comparison.
