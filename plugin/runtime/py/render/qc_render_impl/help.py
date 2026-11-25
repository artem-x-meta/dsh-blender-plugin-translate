# -*- coding: utf-8 -*-
"""Split from qc_render.py; behavior preserved by the facade."""
from .common import *  # noqa: F401,F403
from .parts import PARTS_PALETTE

def qc_render_help():
    return _j({
        "version": QC_RENDER_VERSION,
        "entry": ["blender_rt_plan(op='qc_render_views', args={...})",
                  "blender_rt_plan(op='qc_render_help')  # this quick reference",
                  "blender_rt_plan(op='qc_render_catalog')  # viewpoint catalog (22 names / 4 groups / aliases)",
                  "blender_rt_plan(op='qc_render_device_info')  # measured current device (no render)",
                  "blender_rt_plan(op='qc_render_selftest', args={...})  # self-test: refused in the GUI, run it headless",
                  "blender_rt_headless(file=..., preload='qc,qc_render', script=...)  # long jobs/isolation"],
        "args": {"file": ".blend (GUI needs allow_open_file)", "views": "named/az+el/explicit from+look_at",
                 "res": "[w,h] or a single number", "samples": "default 64", "budget_s|thr": "cumulative render seconds cap",
                 "outdir": "default K.out_dir", "ref_path/ref_box/ref_search": "optional reference comparison (qc.py compare)",
                 "lights": "{key,fill,rim} or false", "lights_mode": "add|only", "margin": "default 1.12",
                 "engine": "keep|eevee|cycles", "tag": "filename prefix", "targets": "objects restricted to those framed here",
                 "mode": "\"views\" (default) | \"parts_color\" (per-part coloring)",
                 "parts_color": "true = mode=\"parts_color\"", "parts_group_by": "object (default) | collection",
                 "parts_flat": "false=flat Principled color (default, has shading) | true=flat Emission color (most accurate color)",
                 "parts_palette": "custom palette [[R,G,B],...] (sRGB 0-255, 12 colors by default)",
                 "parts_legend": "legend .txt path (default <outdir>/parts_color_meta.txt; a same-named .json is written too)",
                 "catalog_ortho": "true = named viewpoints projected per catalog (six-sided orthographic); default false keeps the old convention (perspective)",
                 "view_order": "catalog (default, catalog order + dedupe) | request (strictly the request order)",
                 "strict_views": "true = any unknown view name gives ok:false (by default unknown names are skipped and reported in unknown_views)",
                 # ---- v0.9.1 ----
                 "view_transform": "\"Standard\" (default, the QC convention) | \"scene\" (follow the scene setting, old behavior) | a concrete name (AgX/Filmic/…)",
                 "lock": "default true: acquire the render lock automatically before rendering (cross-process serialization); false disables it",
                 "lock_wait_s": "lock wait cap in seconds (default 120); on timeout → ok:false and nothing is rendered",
                 "lock_dir": "lock base directory (default K.workdir) → lock file <lock_dir>/locks/render.lock",
                 "lock_holder": "holder name (default DSH_SESSION→DSH_RUN_ID→pid-<pid>); **multiple concurrent processes in one session** must each pass an explicit unique name"},
        "views_policy": {
            "default": list(DEFAULT_VIEWS_FALLBACK),
            "default_note": "views omitted/empty = the default 4 viewpoints; v0.8.11 and earlier used %s (pass it explicitly for the old convention)"
                            % ",".join(DEFAULT_VIEWS_LEGACY),
            "unknown_policy": "**non-empty and not a single one resolved → ok:false + nothing is rendered** (no fallback, no silent substitution);"
                              " partly unknown names → the known names still render + requested_count/rendered_count/unknown_count",
            "counts": "the response always has requested_count / rendered_count / unknown_count / no_guess_views / available_views",
            "hint": "unknown names are never guessed: use one of the 22 named viewpoints, or go through the alias table; *_end (muzzle_end/breech_end) is never guessed",
        },
        "named_views": NAMED_VIEWS,
        "view_groups": dict(VIEW_GROUPS),
        "view_menu": view_menu_text(),
        "view_menu_full": view_menu_full_text(),
        "view_aliases": dict(VIEW_ALIASES),
        "view_alias_note": "aliases only tolerate spelling variations (case/underscore/hyphen/word order); no semantic guessing. "
                           "v0.9.1 fix: isoright / isobackright → iso_br (back-right-top, consistent with iso-BR-top in the catalog desc)",
        "no_guess": {"suffix": list(VIEW_NO_GUESS_SUFFIXES), "note": VIEW_NO_GUESS_NOTE,
                     "examples": ["muzzle_end", "breech_end", "side"]},
        "view_transform_note": "QC defaults to Standard (AgX/Filmic push a white background down to ≈0.85, which breaks a whole round of brightness-threshold reading); "
                               "\"scene\" = old behavior; after rendering it is always restored and checked item by item; "
                               "the response and every jsonl line carry view_transform (the value actually in effect)",
        "lock": {"op": "render_lock / qc_render_lock",
                 "actions": {"acquire": "acquire the lock (atomic O_EXCL creation; an expired lock is broken by **timestamp** → stale_broken)",
                             "release": "release the lock (holder mismatch → ok:false; never deletes someone else's lock)",
                             "status": "inspect holder / how long held / remaining TTL / expired or not (read-only)"},
                 "args": {"holder": "holder name (default DSH_SESSION → DSH_RUN_ID → pid-<pid>)",
                          "ttl_s": "lease seconds (default 600; expiry is judged only by the acquired_at timestamp)",
                          "wait_s": "wait cap when the lock is unavailable (default 0 = fail immediately; polls every 0.25s)",
                          "dir": "lock base (default _work_dir()) → <dir>/locks/render.lock"},
                 "auto": "qc_render_views acquires automatically before rendering (lock_wait_s) and releases in finally; "
                         "the response and every jsonl line carry lock = {holder, waited_ms, acquired, stale_broken, path}"},
        "default_views_legacy": list(DEFAULT_VIEWS_LEGACY),
        "default_views_fallback": list(DEFAULT_VIEWS_FALLBACK),
        "parts_palette": [[int(c[0]), int(c[1]), int(c[2])] for c in PARTS_PALETTE],
        "device": "device on each jsonl line = the **measured** render device (Cycles silently falling back to CPU is a ≈7× slower, symptom-free trap); "
                  "when unavailable it is null + device_source, never a guess. The response header also carries a device summary + a one-line device_line",
        "outputs": ["<outdir>/<tag>_<view>.png",
                    "<outdir>/render_views.jsonl (each line {view, ms, bytes, hash, device, view_transform, lock, ...})",
                    "parts_color mode: <outdir>/parts_color_meta.txt (each line `name<TAB>R,G,B<TAB>face count`, "
                    "line count == part count) + a same-named .json",
                    "<lock_dir>/locks/render.lock (render lock file, JSON: holder/pid/acquired_at/ttl_s/note)"],
        "guarantees": ["the camera/three-point lights are created only temporarily inside the process and deleted in finally", "all render settings are restored",
                       "every material slot/temporary material/linked-copy mesh touched by parts_color is restored and **checked item by item**; "
                       "if the check fails it is ok:false straight away",
                       "unknown viewpoint names go into unknown_views as-is (never silently replaced by iso); if not one is recognized → ok:false + empty output",
                       "view_settings.view_transform is restored after rendering and **checked item by item** (not restored → ok:false)",
                       "the render lock is released in finally (also on exceptions; deleted only on holder match)",
                       "the GUI never opens another .blend", "when the budget is exceeded it stops immediately and keeps the frames already rendered"],
    })
