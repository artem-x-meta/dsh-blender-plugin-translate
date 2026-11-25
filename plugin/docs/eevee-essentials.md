# EEVEE working notes (the v0.8.x default engine) and material pipeline pitfalls

> Why this document exists: from v0.8.0 the plugin's default render engine = EEVEE + raytracing (pure GPU, goes through the graphics backend, does not depend on device preferences → headless will not silently fall back to CPU).
> This document merges two sets of measurements in practice: (1) this plugin's engine comparison on a 360-object scene; (2) the EEVEE measurements recorded by a user of the community addon blender_Stylized-Shading-Tools (author lurenjia)
> during an indoor stairwell photo reconstruction task (material_pipeline.md in the repository lurenjia-l/dsh-blender-stylized-shading, technical points quoted).

## 1. Engine facts and expected performance (measured on this machine)

| Item | Value |
|---|---|
| EEVEE's GPU dependency | Pure GPU, goes through the graphics backend (on this machine OPENGL + NVIDIA RTX 4060 Laptop GPU/PCIe/SSE2, GL 4.6 / driver 610.74); there is no CPU fallback |
| Difference from Cycles | Cycles uses the compute_device_type device system (multi-GPU / CPU+GPU possible, driven by preferences); EEVEE does not use it → headless is unaffected by preferences and does not silently degrade |
| Warm-up frame (360 objects / 512x512 / 64 samples) | EEVEE+raytracing 1.35 s vs Cycles GPU 3.13 s (2.3x) |
| First-frame shader compilation | About 16 s with a cold cache; about 2.4 s once the cache is warm → for iteration always use a hot session (blender_rt_worker: you pay compilation only once) |
| Raytracing switch | scene.eevee.use_raytracing (default False); the ray_tracing_method enum on this machine includes SCREEN |
| Headless availability | EEVEE rendering inside blender -b initializes the GPU context by itself (images render normally in practice); but reading gpu.platform requires gpu.init() first (needed only for offscreen drawing) |
| Render harness measurement (v0.8.8, 350 visible meshes / 512×512 / 64 samples) | 3 views 2124 / 798 / 565 ms (the first includes shader compilation) · 3487 ms total · 3 jsonl lines · 36 px margin on all four sides |
| Reproducibility of EEVEE+RT | Two consecutive renders of the same setup: maximum RGB difference 1/255 (0 pixels above 1/255), **the alpha channel is exactly identical**; after switching process/session the difference is ≤5/255 (0.05% of pixels, concentrated on silhouettes and shadow edges) → **judge geometry by alpha; pixel-level md5 cannot serve as a criterion** |

## 2. EEVEE's hard limits and workarounds (community measurements, use them directly)

1. Shader to RGB contains only direct lighting → ambient/world light does not enter the material → shadow areas are pure black.
   - Workaround A (you want an HDR background but do not want it to light the model): two Backgrounds + Mix Shader + Is Camera Ray (the camera sees the HDR, the model is not lit by it);
   - Workaround B (you really need ambient fill): raise the world background strength, or add a shadowless Area ambient light — EEVEE measures in watts, so 300~500 W is needed to be clearly visible.
2. Raytracing only affects indirect light / shadow quality and does not change "direct light only": shadow areas can still be black with raytracing on; do not treat "raytracing on" as "global illumination present".
3. The first-frame compilation cost rises with material complexity: complex NPR node groups cost more than Principled → reuse the same process for iteration.

## 3. Division of labor in the NPR material pipeline (community measurements, avoids pitfalls)

| Node group | What it responds to | What it does | Usage |
|---|---|---|---|
| Main node | Lights (Shader to RGB extracts brightness) | Hard/smooth light-dark separation, tinting of lit/shadow areas, light and shadow brightness | The material's light-dark skeleton (first stage of the pipeline) |
| Light source extension BSDF | Lightgroup ID (light group) | Extracts the color lit by a specified light group and mixes it by Blending | Layered tinting for multiple light sources |

```
main node (light-dark + lit/shadow tinting) → [light source extension group (multi-light tinting, as needed)] → grime/AO/specular/reflection (surface quality) → gradient (optional) → output
```

- When no light group is configured, the light source extension group must be set to Lightgroup ID = -1 (otherwise it responds only to group 0 = not at all).
- Warning: do not chain the "diffuse extension light" after the main node as a brightener — its internal Diffuse computes the light color with the default 0.8 gray, and after Multiply it darkens significantly (measured 214 → 44), and raising that group's Color does not save it either. If it is too dark after chaining, check this first.
- Tinting the lit/shadow areas is the real main coloring channel (do not rely on the diffuse group's Color); under EEVEE the main node output is often too bright, and the measured usual range for lit/shadow brightness is 0.4~0.75.

## 4. Three pitfalls of the gradient group + diagnostic routine (community measurements)

1. The controller must be bound: if Texture Coordinate.002.object inside the group is None → the gradient value is constantly 0 (completely invisible). add_gradient_group creates {object name}_controller automatically and links it; when building the group by hand you must write tc.object = bpy.data.objects[...].
2. Menu[1] decides the coordinate source: object coordinates or empty-object coordinates; choosing wrong + an unbound controller = constant 0; a thin-plate object with no span along its thin axis is also invisible.
3. A group instance's Rotation/Location/Scale may fail to take effect because of interface mapping mismatch → diagnose the actual value of the internal Mapping.001 and the select of Menu Switch.001; if they disagree, edit the internal Mapping directly or rebuild.
4. Diagnostic routine (very important): when you cannot see the effect, first move the camera to a position where the gradient direction is clearly visible and render to verify, and only then go back to the user's camera position to tune parameters — do not misjudge the gradient as broken just because "it cannot be seen from the current camera position".
5. Direction/steepness: the gradient runs along X by default; to run along world Y, rotate the controller so that its local X aligns with world Y (for example rotate -90 degrees around Z), then stretch ctrl.scale.x to control how abrupt the transition is.

## 5. Working with this plugin's toolchain

| Scenario | What to use |
|---|---|
| Iterating on material changes | blender_rt_do (persistent kernel; after changing parameters, see:true returns a frame immediately) or blender_rt_worker (hot session, EEVEE compilation paid only once) |
| Batch image output / multi-camera comparison | blender_rt_headless (the EEVEE+raytracing preamble is injected by default; engine="cycles" switches back) |
| Judging "does the change look right" | blender_rt_plan(op="qc_compare"): IoU/Dice/missing-excess area/boundary distance + comparison image; the receipt carries engine_at_qc (comparable only within the same engine) |
| Trying parameters without breaking things | blender_rt_txn (mark → change → revert; snapshot before big changes) |
| Running long scripts | blender_rt_do(file="//scripts/xxx.py") (supports //rel, /mnt/..., D:/...) |

> **Acknowledgements**: the EEVEE hard limits, the NPR material pipeline division of labor and the gradient group pitfalls in sections 2–4 of this document come from the measurements recorded by **@lurenjia-l**
> (`material_pipeline.md` in the repository [lurenjia-l/dsh-blender-stylized-shading](https://github.com/lurenjia-l/dsh-blender-stylized-shading)).
> That note spells out the pitfalls that most easily waste a few hours on EEVEE (Shader to RGB containing only direct light, the diffuse extension light used as a brightener pushing 214 down to 44,
> an unbound gradient group controller causing a constant 0, and so on); we added them to this document accordingly and rewrote them into usage for this plugin's channel — thanks to the author for being willing to publish these details.
> The numbers on this plugin's side (1.35 s / 3.13 s / 2.3x / cold first frame 16 s) are all measured on this machine.

> Status update (2026-09-14): the third-party addon described in that material_pipeline.md (blender_Stylized-Shading-Tools) **has been deleted and is no longer available**.
> However the **principles and pitfalls** it records (main node / light source extension BSDF division of labor, the Lightgroup ID rule, Shader to RGB containing only direct light, gradient group binding and mapping-mismatch diagnostics)
> **apply equally to hand-built NPR node groups**, so this section is kept.
