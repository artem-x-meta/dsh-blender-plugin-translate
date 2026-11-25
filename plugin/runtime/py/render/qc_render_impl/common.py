# -*- coding: utf-8 -*-
"""DSH built-in render harness (v0.9.1: 93 feedback A1/A2/E1/B1-B2 — unknown names hard-fail / QC defaults to Standard / render lock / callable API)
— one call produces multi-view QC images.

External feedback, verbatim: inputs {file, views[], res, samples, thr, outdir} → precise framing by bbox
+ fixed three-point light + per-image jsonl timing + budget verdict — "this is the thing every modeling task has to rewrite".

v0.8.11 brings three things over from SpatiaOS/Procedura (MIT; local mirror .procedura-ref/, evaluation in docs/procedura-fusion-analysis.md)
(criteria and algorithms only, not its TS/OpenSCAD stack):
  A. per-part coloring (src/render/parts_color.ts + scripts/_render_parts_color_blender.py)
     → mode="parts_color": one color per part + 12-color cycling palette + legend file + **full restore after rendering**;
  B. measured device line (src/render/device_line.ts + scripts/_blender_gpu.py)
     → every jsonl line records device: Cycles **silently falls back to CPU** (≈7× slower, zero symptoms),
       "which backend actually ran this image" must land in the artifact; if unavailable, null + device_source, never a guess;
  C. view catalog + alias normalization (src/render/views.ts)
     → 22 named views folded into 4 catalog groups + alias tolerance + unknown names echoed back as-is
       (older versions **silently** rendered unrecognized names as iso: the output looked fine, but the angle was not the one named, and the report could not show it).

v0.9.1 comes from the shipped project rifle-build "93 feedback" — two P0s (A1/A2, silent failures polluting the evidence chain) + one P2 (E1) + API shape (B1/B2):
  A1. **unknown view names are no longer silently substituted** (v0.8.11 behavior: 4 names, not one recognized → still ok:true and silently rendered
      iso/front/right/top — right filenames, wrong angles, invisible to the caller):
        · views **non-empty and not a single one resolved** → **ok:false**, returning unknown_views (original spelling) /
          available_views (the 22 named views) / view_menu (grouped quick-reference text) / requested_count /
          rendered_count(=0) / hint — **renders nothing, no fallback substitution either**;
        · views **omitted/empty** → the default 3 views, same as v0.8.11 (iso/front/right, see DEFAULT_VIEWS_LEGACY).
          To use Procedura's 4-view set (iso/front/right/top), **pass explicitly** those four DEFAULT_VIEWS_FALLBACK names
          — the patched version does not silently change the default artifact set; explicit views semantics are unchanged;
        · some unknown names → known names still render, but the response **always** carries requested_count / rendered_count / unknown_count
          (a teammate hit "12 names, only 8 rendered, no error");
        · added **spelling-only** aliases (side_left / left_view / topdown … → canonical names, see VIEW_ALIASES);
          semantically ambiguous ones are never guessed — `*_end` (muzzle_end / breech_end) is **never mapped** (VIEW_NO_GUESS_SUFFIXES),
          it goes into unknown_views for the caller to map explicitly from its own catalog (muzzle_end→front in a weapon context is the caller's judgment, the plugin does not guess for it).
  A2. **QC rendering defaults to view_transform="Standard"** (v0.8.11 default null = follow the scene; Blender 5.x ships AgX, which
      crushes a pure white background to ≈0.85, so any analysis that "crops references / computes silhouettes by brightness threshold" fails wholesale):
        · default = "Standard" (QC convention: strip the AgX/Filmic wash so threshold reading is reliable);
        · "scene" = follow the scene settings (old behavior, for beauty images); a concrete name ("AgX"/"Filmic"/"Standard") = use that one;
        · after rendering, the scene view_settings.view_transform **must be restored** (checked item by item; not restored → ok:false,
          the same discipline as the parts_color restore: leaving the scene dirty is far worse than rendering one image less);
        · the response and **every jsonl line** carry view_transform (the one actually in effect); "scene" while the scene is not Standard
          yields scope_warnings: "currently AgX, threshold reading needs manual correction"; a wrong name / absent on this machine → ok:false before rendering
          (no silently rendering with a different color transform).
  E1. **built-in render lock** (replaces the ad-hoc render_lock.py each member wrote: concurrent processes running EEVEE fight over the same GPU, measured someone waiting 48s for the lock):
        · render_lock(action="acquire"|"release"|"status", holder, ttl_s, wait_s, note);
          lock file <workdir>/locks/render.lock (workdir = K.workdir / K.out_dir, i.e. the working directory the processes share),
          contents JSON {holder, pid, acquired_at, ttl_s, note}; **expiry is judged by timestamps alone** (the only reliable cross-process criterion,
          process liveness is not enough); when a stale lock is broken it returns stale_broken:true and records a warning;
        · qc_render_views **acquires automatically** before rendering (lock_wait_s defaults to 120s; lock=false turns it off),
          releases in finally (also on exceptions; only deletes when the holder matches); cannot get the lock → ok:false (no silently rendering a batch of inflated timings);
        · the response and every jsonl line carry lock {holder, waited_ms, acquired, stale_broken, path} — timing is auditable.
  B1/B2. K.dsh_qc_render_api is a **dict subclass** (_DshApi): supports both api["render_views"] (old style, returns str)
      and api("render_views", {...}) / api({...}) (returns the **parsed dict**); api["dispatch"](op, json_str)
      still returns **str** (engine contract unchanged).

The API hangs off K.dsh_qc_render_api. Two entry points:
    blender_rt_plan(op="qc_render_views", args={...})                    # via the qc_render module (engine routing)
    blender_rt_headless(file=..., preload="qc,qc_render", script=...)    # headless/job layer (long work, naturally isolated)

Parameters (all have defaults except views):
    file        .blend path. When it differs from the current file: background -b opens it directly; the GUI refuses by default (it would displace the user's scene),
                needs allow_open_file=true to open
    views       ["front","iso","top"] or [{"name","az","el","from","look_at","lens","ortho","res","margin"}]
                named views: front/back/left/right/top/bottom/iso/iso_l/iso_back/front_high (all 22 names in
                qc_render_catalog / view_menu); you can also write "az=35,el=20"; omitted/empty = ["iso","front","right"]
                (same as v0.8.11; for the 4-view set pass iso/front/right/top explicitly).
                v0.9.1 (A1): **not one name recognized** → ok:false and nothing is rendered (no more silent fallback)
    res         [w,h] or a single number (default [512,512])
    samples     sample count (EEVEE=taa_render_samples / Cycles=samples, default 64)
    budget_s    cumulative render-seconds cap (alias thr). Stops immediately when exceeded: images and jsonl lines already produced are kept, within_budget=false
    outdir      output directory (Windows or WSL paths both accepted, default K.out_dir)
    ref_path    optional reference image: each render calls qc.py compare to compute IoU/profile difference and writes it to jsonl (needs qc.py injected)
    ref_box     reference image crop box [x0,y0,x1,y1]; or {"front":[..], "iso":[..]} to distinguish by view
    ref_search  whether reference comparison uses search alignment (default false = fixed alignment convention, prevents score gaming)
    lights      {"key":4.0,"fill":1.2,"rim":2.5} or false to turn off; by default layered on top of the scene's existing lights
    lights_mode "add" (default) | "only" (temporarily masks other lights in the scene, restores after rendering)
    margin      framing margin (default 1.12; larger leaves more empty space)
    engine      "keep" (default, follow the process's current engine) | "eevee" (EEVEE + raytracing) | "cycles"
    view_transform  color transform (from v0.9.1 **default = "Standard"**: the QC convention drops the AgX/Filmic wash so threshold reading is reliable;
                "scene" = follow the scene settings (v0.8.11 old behavior, for beauty images); a concrete name = use that one (e.g. "AgX").
                Either way the scene settings are restored after rendering; the response and every jsonl line record the value actually in effect)
    warmup      default true: render one frame to warm up first (EEVEE shader compilation), **not timed, not in jsonl, not counted against the budget** — only then is single-image timing a clean number
    ladder      quality ladder (v0.8.10): [{"samples":64,"scale":1.0},{"samples":32,"scale":0.75},…];
                with per_view_budget_s, a view that exceeds its budget is re-rendered one step lower, each step recorded (later views stay on that step)
    aabb/focus  world-space framing (v0.8.10): aabb=[x0,y0,z0,x1,y1,z1] or focus="x,y,z,r" (top level or per view)
    sheet       when >1, tiles the rendered images into an N-cell contact sheet (needs the montage module; the result gives the sheet path and per-cell metrics)
    tag         output filename prefix (default "views"); jsonl defaults to <outdir>/render_views.jsonl

v0.8.11 new parameters (no old parameter touched):
    mode        "views" (default) | "parts_color" (per-part coloring); parts_color=true is equivalent to mode="parts_color"
    parts_group_by  parts_color grouping: "object" (default, one color per object) | "collection" (one color per collection)
    parts_flat  default false = Principled flat color (shaded, so interpenetration / floaters / orientation are visible);
                true = Emission flat color (unaffected by lights, on-image color ≈ legend color, good for reading the image against the color key)
    parts_palette  custom palette [[R,G,B], ...] (sRGB 0-255; 12 colors by default, see PARTS_PALETTE)
    parts_legend  legend .txt path (default <outdir>/parts_color_meta.txt; a same-named .json with the details is written alongside)
    catalog_ortho  default false: named views keep the old convention (perspective), the catalog's ortho is only a semantic annotation;
                pass true to project per the catalog (six faces orthographic, the rest perspective) — old images and historical scores stay pixel-for-pixel comparable
    view_order  "catalog" (default: string named views rendered in catalog order + deduplicated) | "request" (strictly request order)
    strict_views  default false: unknown view names go to unknown_views and are skipped (known views render as usual); true = any unknown name makes ok:false

v0.9.1 new parameters (no old parameter touched):
    lock        default true: acquire the render lock before rendering (cross-process serialization, so timing is auditable); false/0/"off" = off
    lock_wait_s max seconds to wait for the lock (default 120); not acquired → ok:false (no silently rendering a batch of inflated timings)
    lock_dir    the lock's working directory (default K.workdir / K.out_dir) → lock file <lock_dir>/locks/render.lock
                the lock primitive is also callable directly: K.dsh_qc_render_api("render_lock", {"action": "status"})
    lock_holder holder name (default DSH_SESSION → DSH_RUN_ID → pid-<pid>); **when running several render processes concurrently in the same session
                you must pass different names** — otherwise a same-named holder cannot distinguish "who holds it", and an edge case (the original
                process only comes back to release after the TTL expired and the lock was broken) deletes someone else's lock

Artifacts: <outdir>/<tag>_<view>.png × N + <outdir>/render_views.jsonl (each line {view, ms, bytes, hash, device, ...})
      parts_color mode additionally writes <outdir>/parts_color_meta.txt (legend: each line `name<TAB>R,G,B<TAB>face count`,
      data lines only, line count == part count, handy for `wc -l` cross-checking) + a same-named .json (palette / grouping / restore self-check details)

Discipline (consistent with the project's other modules):
  · the camera and three-point light are **created temporarily inside this process only**; deleted in finally, and every scene render setting is restored;
  · never writes .blend, never touches the user's camera, never touches the user's lights (except lights_mode="only", also restored after rendering);
  · in the GUI it does not open another .blend by default — long work goes to the headless/job layer (naturally isolated).
  · v0.8.11: material slots overridden by parts_color / temporary materials / linked duplicate meshes **are all restored and checked item by item**,
    and a failed check is an immediate ok:false (leaving the scene dirty is far worse than rendering one image less — this is the project's historical lesson);
  · v0.8.11: view names are tolerated but **not guessed**: unknown names go into unknown_views as-is, never silently replaced with iso.
  · v0.9.1: **unrecognized means failure** (not one recognized → ok:false + nothing rendered); acquire the lock before rendering, release it in finally;
    after rendering the color transform is checked item by item and restored, not restored → ok:false.
"""
import bpy
import hashlib as hashlib
import json
import math as math
import os
import tempfile
import time as time

from mathutils import Vector as Vector

import numpy as np  # noqa: F401  # re-exported to the split qc_render modules


QC_RENDER_VERSION = 3      # v0.9.1: A1 unknown names hard-fail / A2 QC defaults to Standard / E1 render lock / B1-B2 callable API
DEFAULT_RES = (512, 512)
# fixed three-point light (SUN in the W/m² class of intensity, independent of scene scale): key 3.2 / fill 1.0 / rim 2.4
DEFAULT_LIGHTS = {"key": 3.2, "fill": 1.0, "rim": 2.4}
# fixed angles relative to the **camera azimuth** (degrees): key right-front-up · fill left-front-flat · rim back contour
LIGHT_ANGLES = {"key": (35.0, 45.0), "fill": (-50.0, 8.0), "rim": (165.0, 30.0)}
LIGHT_SOFT = {"key": 5.0, "fill": 14.0, "rim": 6.0}

# ---------------------------------------------------------------- v0.8.11 (C): view catalog + alias normalization
# Why it exists (the lesson from Procedura src/render/views.ts): view names used to be scattered in NAMED_VIEWS, and when a model wrote
# "isometric" / "iso-FR-top" / "isoright" none of them hit the named table → fell into az/el parsing → parsing failed → **silently fell back to iso**:
# the output looked normal, but the rendered angle was not the one named, and historical reports could not show it (the same class of accident as this project's 234 fake-evidence incident).
# The catalog is the single source of truth: NAMED_VIEWS is derived from it (old names and old angles unchanged item by item, see the LEGACY_NAMED_VIEWS frozen snapshot),
# aliases are **spelling** tolerance only; semantically ambiguous names (like "side") are not guessed, they all go to unknown_views.
# The ortho field is a semantic annotation (Procedura's six faces are ortho=true) and is **not applied by default** — old calls (views=["front"])
# have always been perspective, and changing that would make old images and historical scores incomparable pixel by pixel; to project per the catalog pass catalog_ortho=true.
VIEW_CATALOG = [
    # ── orthographic six faces (group=face): six axis-aligned faces ──
    {"name": "front", "group": "face", "az": -90.0, "el": 0.0, "ortho": True, "desc": "front (camera at −Y looking +Y)"},
    {"name": "back", "group": "face", "az": 90.0, "el": 0.0, "ortho": True, "desc": "back (+Y)"},
    {"name": "left", "group": "face", "az": 180.0, "el": 0.0, "ortho": True, "desc": "left (−X)"},
    {"name": "right", "group": "face", "az": 0.0, "el": 0.0, "ortho": True, "desc": "right (+X)"},
    {"name": "top", "group": "face", "az": 0.0, "el": 90.0, "ortho": True, "desc": "top (+Z, looking straight down)"},
    {"name": "bottom", "group": "face", "az": 0.0, "el": -90.0, "ortho": True, "desc": "bottom (−Z, looking straight up)"},
    # ─ isometric corners (group=corner): 8 three-quarter hero positions (perspective); iso is the historical default name (Procedura calls it isometric) ──
    {"name": "iso", "group": "corner", "az": -45.0, "el": 25.0, "ortho": False,
     "desc": "front-right-top 3/4 (default hero position; Procedura names isometric / iso-FR-top)"},
    {"name": "iso_l", "group": "corner", "az": -135.0, "el": 25.0, "ortho": False, "desc": "front-left-top 3/4 (iso-FL-top)"},
    {"name": "iso_br", "group": "corner", "az": 45.0, "el": 25.0, "ortho": False, "desc": "back-right-top 3/4 (iso-BR-top; new)"},
    {"name": "iso_back", "group": "corner", "az": 135.0, "el": 25.0, "ortho": False, "desc": "back-left-top 3/4 (iso-BL-top)"},
    {"name": "iso_fr_bot", "group": "corner", "az": -45.0, "el": -25.0, "ortho": False, "desc": "front-right-bottom 3/4 (looking up; new)"},
    {"name": "iso_fl_bot", "group": "corner", "az": -135.0, "el": -25.0, "ortho": False, "desc": "front-left-bottom 3/4 (new)"},
    {"name": "iso_br_bot", "group": "corner", "az": 45.0, "el": -25.0, "ortho": False, "desc": "back-right-bottom 3/4 (new)"},
    {"name": "iso_bl_bot", "group": "corner", "az": 135.0, "el": -25.0, "ortho": False, "desc": "back-left-bottom 3/4 (new)"},
    # ── eye-level diagonals (group=diagonal): two adjacent faces, el=0 (no pitch) ──
    {"name": "front_right", "group": "diagonal", "az": -45.0, "el": 0.0, "ortho": False, "desc": "eye level, between front and right (new)"},
    {"name": "front_left", "group": "diagonal", "az": -135.0, "el": 0.0, "ortho": False, "desc": "eye level, between front and left (new)"},
    {"name": "back_right", "group": "diagonal", "az": 45.0, "el": 0.0, "ortho": False, "desc": "eye level, between back and right (new)"},
    {"name": "back_left", "group": "diagonal", "az": 135.0, "el": 0.0, "ortho": False, "desc": "eye level, between back and left (new)"},
    # ── hero pitch (group=tilt): front/right ± elevation. front_high / right_high are historical names, **the angles must not change** ──
    {"name": "front_high", "group": "tilt", "az": -90.0, "el": 35.0, "ortho": False,
     "desc": "front looking down 35° (historical name, angle kept; Procedura's front-high is 15°, not followed here)"},
    {"name": "front_low", "group": "tilt", "az": -90.0, "el": -15.0, "ortho": False, "desc": "front looking up 15° (new)"},
    {"name": "right_high", "group": "tilt", "az": 0.0, "el": 35.0, "ortho": False, "desc": "right looking down 35° (historical name)"},
    {"name": "right_low", "group": "tilt", "az": 0.0, "el": -15.0, "ortho": False, "desc": "right looking up 15° (new)"},
]
VIEW_GROUPS = [("face", "orthographic six faces (axis-aligned faces; the catalog marks ortho, but the old perspective convention still applies by default)"),
               ("corner", "isometric corners (perspective 3/4 hero positions)"),
               ("diagonal", "eye-level diagonals (two adjacent faces, no pitch)"),
               ("tilt", "hero pitch (front/right ± elevation)")]
NAMED_VIEWS = dict((v["name"], (v["az"], v["el"])) for v in VIEW_CATALOG)   # old interface: name → (az, el)
VIEW_ORDER = [v["name"] for v in VIEW_CATALOG]                              # catalog order = render order (after dedup)
VIEW_ORTHO = dict((v["name"], bool(v["ortho"])) for v in VIEW_CATALOG)
VIEW_DESC = dict((v["name"], str(v["desc"])) for v in VIEW_CATALOG)
VIEW_GROUP_OF = dict((v["name"], str(v["group"])) for v in VIEW_CATALOG)
# old-convention frozen snapshot (the v0.8.8 NAMED_VIEWS literals): the self-check compares item by item, so "converging the catalog" cannot slip in a changed old angle
LEGACY_NAMED_VIEWS = {"front": (-90.0, 0.0), "back": (90.0, 0.0), "right": (0.0, 0.0), "left": (180.0, 0.0),
                      "top": (0.0, 90.0), "bottom": (0.0, -90.0), "iso": (-45.0, 25.0), "iso_l": (-135.0, 25.0),
                      "iso_back": (135.0, 25.0), "front_high": (-90.0, 35.0), "right_high": (0.0, 35.0)}
# aliases (keys already normalized: lowercase + spaces/underscores/hyphens stripped) → canonical name. **Spelling** tolerance only, no semantic guessing.
# v0.9.1 (93 feedback A1-4) adds two kinds:
#   ① pure spelling synonyms (side_left / left_view / topdown / front_view …) — accepted only when the meaning is unambiguous;
#   ② fixing two historical mis-mappings: isoright / isobackright used to point at iso (front-right-top) and iso_back (back-left-top),
#      but the catalog's iso_br desc is exactly "iso-BR-top" (back-right-top) → they all converge on iso_br (consistent with isobrtop).
# semantically ambiguous ones are **not guessed** (side / muzzle / breech / any `*_end`): see VIEW_NO_GUESS_SUFFIXES and
# qc_render_catalog.no_guess — the caller must map explicitly from its own project's catalog (e.g. a weapon's muzzle_end → front).
VIEW_ALIASES = {"isometric": "iso", "isofrtop": "iso", "isofrontright": "iso",
                "isoright": "iso_br", "isobrtop": "iso_br", "isobackright": "iso_br",
                "isofltop": "iso_l", "isofrontleft": "iso_l", "isoleft": "iso_l",
                "isobltop": "iso_back", "isobackleft": "iso_back",
                "isofrbot": "iso_fr_bot", "isoflbot": "iso_fl_bot",
                "isobrbot": "iso_br_bot", "isoblbot": "iso_bl_bot",
                # —— v0.9.1 concatenation/word-order spelling tolerance (only these three styles, no semantic association) ——
                "sideleft": "left", "leftside": "left", "leftview": "left",
                "sideright": "right", "rightside": "right", "rightview": "right",
                "frontview": "front", "backview": "back",
                "topview": "top", "topdown": "top", "bottomview": "bottom"}
# v0.9.1 (A1): the **no-guess** discipline — names ending with these suffixes after normalization are never mapped (even if someone adds them to the alias table later).
# Why listed separately: `muzzle_end` / `breech_end` look like "some end face", but which orthographic face they map to is **project semantics**
# (which way the muzzle points, which side counts as front); if the plugin guesses once on the caller's behalf, it leaves an image in the report with "right filename, wrong angle".
VIEW_NO_GUESS_SUFFIXES = ("end",)
VIEW_NO_GUESS_NOTE = ("the suffix *_end (muzzle_end / breech_end …) and semantically ambiguous names (side / muzzle …) are never guessed: "
                      "they go into unknown_views as-is, please map them explicitly from this project's view catalog (e.g. muzzle_end → front)")

# v0.9.1 (A1) final: **omitted/empty views still use v0.8.11's old default (3 images)** — the patched version does not silently change the default artifact set.
DEFAULT_VIEWS_LEGACY = ["iso", "front", "right"]
# Procedura's 4-view set (iso/front/right/top): kept exported, callers use it when they **explicitly** want it.
# Note: v0.9.0 used to fall back to it for "all names unknown"; from v0.9.1 that case is ok:false (A1), so it is now just "a recommended set of views".
DEFAULT_VIEWS_FALLBACK = ["iso", "front", "right", "top"]



import sys as _sys_kit
_KIT = getattr(_sys_kit.modules.get("dsh_rt_kernel"), "dsh_kit", None)
if _KIT is None:
    raise RuntimeError("qc_render needs the shared kernel K.dsh_kit (injected by KERNEL_BOOTSTRAP)")


_j = _KIT.j  # shared kernel (the original self-contained implementation was deleted, see S1)
def _unpack_args(args):
    """args unpacking (dispatch and qc_render_views share the same convention):
    JSON string / None / {"args": {...}} wrapped one extra level → dict (copying v0.8.8's one-level-wrapped unpacking)."""
    a = args
    if isinstance(a, str):
        s = a.strip()
        a = json.loads(s) if s else {}
    if not isinstance(a, dict):
        return {}
    if "args" in a and isinstance(a["args"], dict):
        merged = dict(a["args"])
        merged.update((k, v) for k, v in a.items() if k != "args")
        a = merged
    return dict(a)


def _norm_view_name(s):
    """Normalize a view name: lowercase + alphanumerics only ("iso_l" / "iso-L" / "iso l" all → "isol")."""
    return "".join(ch for ch in str(s).strip().lower() if ch.isalnum())


_NORM2CANON = dict((_norm_view_name(n), n) for n in VIEW_ORDER)


def _canon_view(name):
    """Spelling → canonical name; returns None when nothing matches (**no guessing**: let the caller report unknown_views).

    v0.9.1 (A1): the **no-guess** discipline runs first — names ending with `*_end` after normalization are None outright (no alias-table fallback).
    """
    k = _norm_view_name(name)
    if not k:
        return None
    if k.endswith(VIEW_NO_GUESS_SUFFIXES):
        return None                       # no guessing: muzzle_end / breech_end … are mapped explicitly by the caller from the catalog
    if k in _NORM2CANON:
        return _NORM2CANON[k]
    return VIEW_ALIASES.get(k)


def _no_guess_hit(name):
    """Whether this name was blocked by the **no-guess discipline** (used in the response to distinguish "no such name" from "deliberately not guessed")."""
    k = _norm_view_name(name)
    return bool(k) and k.endswith(VIEW_NO_GUESS_SUFFIXES)



def _is_azel_spec(s):
    """Old-convention "az=35,el=20" syntax still gets parsed (v0.8.8 behavior, must not break); every other unknown name goes to unknown_views."""
    t = str(s).lower().replace(" ", "")
    return ("az=" in t) or ("el=" in t)


def resolve_view_names(names):
    """String view-name list → {"names": canonical names [catalog order + dedup], "unknown": original spelling, "aliases": hit records,
    "deduped": duplicate items, "no_guess": original spelling blocked by the no-guess discipline}.

    Procedura convention (src/render/views.ts resolveViews): normalize to canonical names first, unknown names are **left as-is** for the caller to alarm on,
    known names are output in **catalog order** — the order is fixed, so results are comparable across runs and sessions.
    v0.9.1 (A1): this **no longer** says "fall back to DEFAULT_VIEWS_FALLBACK when everything is invalid" — qc_render_views decides
    "non-empty and not one recognized = ok:false" (only empty/omitted uses the default); resolve itself is pure normalization and does not fall back for the caller.
    """
    want, unknown, aliases, deduped, no_guess = [], [], [], [], []
    seen = set()
    for raw in (names or []):
        s = str(raw).strip()
        if not s:
            continue
        canon = _canon_view(s)
        if canon is None:
            unknown.append(str(raw))          # keep the **user's original spelling**, not the normalized one
            if _no_guess_hit(s):
                no_guess.append(str(raw))
            continue
        if _norm_view_name(s) != _norm_view_name(canon):
            aliases.append({"requested": str(raw), "resolved": canon})
        if canon in seen:
            deduped.append(str(raw))
            continue
        seen.add(canon)
        want.append(canon)
    return {"names": [n for n in VIEW_ORDER if n in seen], "unknown": unknown,
            "aliases": aliases, "deduped": deduped, "no_guess": no_guess}


def view_menu_text():
    """Quick-reference text: every named view listed by group (feeds qc_render_help's view_menu, and lets prompts name views directly)."""
    lines = []
    for g, label in VIEW_GROUPS:
        names = [str(v["name"]) for v in VIEW_CATALOG if str(v["group"]) == g]
        lines.append("  • %s: %s" % (label, ", ".join(names)))
    return "\n".join(lines)


def view_menu_full_text():
    """view_menu_text() + alias table + the **no-guess** discipline (v0.9.1 A1): an in-place answer to "what do I do when the name is misspelled"."""
    return (view_menu_text()
            + "\n  aliases (pure spelling tolerance): " + ", ".join("%s→%s" % (k, v) for k, v in sorted(VIEW_ALIASES.items()))
            + "\n  no guessing: " + VIEW_NO_GUESS_NOTE)



def qc_render_view_catalog():
    """View catalog (machine-readable): groups / az,el / ortho semantics / human-readable descriptions / aliases / fallback views."""
    return _j({"ok": True, "version": QC_RENDER_VERSION,
               "groups": [{"id": g, "label": label,
                           "views": [dict(v) for v in VIEW_CATALOG if str(v["group"]) == g]}
                          for g, label in VIEW_GROUPS],
               "order": list(VIEW_ORDER), "aliases": dict(VIEW_ALIASES),
               "alias_note": "aliases are **spelling** tolerance only (case/underscore/hyphen/word order insensitive), no semantic guessing; "
                             "v0.9.1 fix: isoright / isobackright → iso_br (in the catalog iso-BR-top = back-right-top)",
               "no_guess": {"suffix": list(VIEW_NO_GUESS_SUFFIXES), "note": VIEW_NO_GUESS_NOTE,
                            "examples": ["muzzle_end", "breech_end"]},
               "default_views": list(DEFAULT_VIEWS_LEGACY),
               "default_views_fallback": list(DEFAULT_VIEWS_FALLBACK),
               "default_views_legacy": list(DEFAULT_VIEWS_LEGACY),
               "default_views_note": "views omitted/empty = default_views_legacy (3 images, same as v0.8.11); for the 4-view set pass the four default_views_fallback names explicitly",
               "view_transform_default": "Standard",
               "view_transform_note": "QC convention defaults to Standard (AgX/Filmic crush a white background to ≈0.85, breaking threshold reading); "
                                      "pass \"scene\" to follow the scene settings; always restored after rendering",
               "unknown_views_policy": "views non-empty and not one recognized → ok:false (nothing rendered, no fallback substitution); "
                                       "some unknown names → known names render + requested_count/rendered_count/unknown_count",
               "lock": {"op": "render_lock", "path": "<workdir>/locks/render.lock",
                        "actions": ["acquire", "release", "status"],
                        "note": "cross-process render lock (expiry judged by timestamps); qc_render_views acquires automatically before rendering and releases in finally"},
               "legacy_named_views": dict(LEGACY_NAMED_VIEWS),
               "menu_text": view_menu_full_text(),
               "ortho_note": "the catalog's ortho is a semantic annotation; actual projection follows the old convention (perspective) by default, "
                             "pass catalog_ortho=true to project per the catalog"})


def _kernel():
    import sys
    return sys.modules.get("dsh_rt_kernel")


def _win(path):
    """WSL → Windows-side path (Blender is a Windows process). Uses K.win_path when available."""
    K = _kernel()
    if K is not None and hasattr(K, "win_path"):
        try:
            return K.win_path(path)
        except Exception:
            pass
    s = str(path)
    if s.startswith("/mnt/") and len(s) > 6:
        return s[5].upper() + ":" + chr(92) + s[7:].replace("/", chr(92))
    return s


def _out_dir():
    K = _kernel()
    d = getattr(K, "out_dir", None) if K is not None else None
    return d or os.path.join(tempfile.gettempdir(), "dsh_qc_render")


def _work_dir():
    """The **working directory** (not a single call's outdir): the base for the v0.9.1 (E1) render lock.

    Uses K.workdir (injected by the engine = K.out_dir; GUI/headless/worker processes under the same launcher **share one** working directory,
    so the lock is visible across processes — concurrent parties are separate headless processes, and only a shared filesystem can coordinate them),
    then falls back to K.out_dir, the DSH_OUTDIR environment variable, the temp directory.
    """
    K = _kernel()
    for attr in ("workdir", "out_dir"):
        d = getattr(K, attr, None) if K is not None else None
        if d:
            return str(d)
    return os.environ.get("DSH_OUTDIR") or os.path.join(tempfile.gettempdir(), "dsh_qc_render")


# ---------------------------------------------------------------- v0.9.1 (A2): list of color transforms available on this machine
# Why not bl_rna's enum_items: in Blender 5.x view_transform is an OCIO **dynamic enum**, and measurement shows
# `bl_rna.properties["view_transform"].enum_items` returns only ['NONE'] (no complete list); "try writing each + read back"
# is the only reliable criterion (assigning a name this machine lacks raises enum not found), and the original value is written back afterwards.
VT_PROBE_CANDIDATES = ("Standard", "AgX", "Filmic", "Filmic Log", "Khronos PBR Neutral", "Raw",
                       "False Color", "Linear", "Linear Rec.709", "sRGB", "None")


def _vt_options():
    """Measure the view_transform names available on this machine (try writing + read back, then **restore the original value**)."""
    vs = getattr(bpy.context.scene, "view_settings", None)
    if vs is None:
        return []
    cur = str(getattr(vs, "view_transform", "") or "")
    opts = []
    try:
        for c in VT_PROBE_CANDIDATES:
            try:
                vs.view_transform = c
                if str(getattr(vs, "view_transform", "")) == c and c not in opts:
                    opts.append(c)
            except Exception:
                pass
    finally:
        if cur:
            try:
                vs.view_transform = cur
            except Exception:
                pass
    return opts


# ---------------------------------------------------------------- v0.9.1 (E1): cross-process render lock
# Why this is done on the Python side (93 feedback E1): concurrent parties are **separate headless processes** with no shared memory, only a shared filesystem;
# measurement shows that when several processes fight over one GPU, single-image timings are inflated (someone waited 48s for the lock), so members could only write their own render_lock.py.
# The **only reliable criterion for judging expiry is the timestamp in the lock file** (across processes you cannot rely on "is the process still alive": it may have been kill -9'd,
# the pid may belong to a same-named process in another container, or it may be running a render while unresponsive); so TTL is always computed from acquired_at,
# and when acquired_at cannot be read it falls back to the file mtime (marking age_source, without pretending to know).
LOCK_POLL_S = 0.25
LOCK_DEFAULT_TTL_S = 600.0




__all__ = [name for name in list(globals()) if not name.startswith("__")]
