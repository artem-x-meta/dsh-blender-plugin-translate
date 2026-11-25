# -*- coding: utf-8 -*-
"""DSH transactions / rollback (v0.7.0) — two levels: file-level snapshots + object-level mark/revert.

The API hangs off K.dsh_txn_api. Design trade-offs (landed against the external feedback "no transactions/rollback"):

  File level  snapshot(label) / restore(label, into="auto", backup=True)
      snapshot uses bpy.ops.wm.save_as_mainfile(copy=True) — it **does not change the current filepath**;
      the file lands in <K.out_dir>/snapshots/<label>.blend, and "the filepath at snapshot time" is recorded.
      When to use: "drop a marker before tearing the whole scene down"; cost: MB-scale disk writes (noticeable on large scenes).

      filepath semantics of restore (fixed in v4; external feedback: in older versions, after a restore "the first save wrote into the snapshot directory"):
        open_mainfile(snapshot) moves **the whole session** onto the snapshot file, so bpy.data.filepath becomes the snapshot path —
        the original file never actually moved, but any later save fell into snapshots/, which is surprising. Now:
        · into="auto" (default): after loading the snapshot, **return to the file the snapshot came from** (the recorded filepath, else the current file),
          i.e. "restore into the original file"; the session stays attached to its own project and a save writes back where it belongs.
        · into="snapshot": non-destructive mode — load the snapshot only and **not write a single byte to the original file**;
          the session explicitly stays on the snapshot path, and the receipt gives next_save_goes_to so you know where a save would land.
        · into="original": requires a writable original file, otherwise ok:false (no silent degradation).
        When no target can be found (unsaved scene / both snapshot and session inside the snapshot directory) it **does not write blindly**: it keeps the snapshot path plus an explicit warning.
        backup=True (default): a pre_restore snapshot is taken automatically before restore (restore discards the current unsaved state);
        when the session is dirty and the original file is about to be overwritten, an extra **on-disk copy** of the original file is saved (_pre_restore_file_*) — both can be brought back with list/restore.

  Object level  mark(label, objects=[...]) / revert(label)
      Records only the object's transform / material slots / visibility / modifier flags in memory (JSON-friendly); revert writes them back in place.
      When to use: "change one thing and compare"; **limit: no topology changes** (after a boolean / join / face deletion there is no way back),
      and no uv / vertex position changes either — for that level of rollback use a file-level snapshot.

  Pending edits (v0.9.0 / #12)  edit_begin / edit_check / edit_accept / edit_revert / edit_status
      Turns "change a step and look" into a protocol: **an edit must be verified before it is accepted** (upstream Procedura src/tools/edit-transaction.ts
      accept_edit / revert_edit, landed onto bpy).
        edit_begin(label, op, targets, note)  → records a transform/materials/visibility snapshot of the target objects at that moment and attaches a pending
        edit_check(kind, result, note)        → registers one review (kind = audit / qc / measure / render ...)
        edit_accept(verified)                 → verified is **required** (one line saying "what was looked at, what was confirmed"),
                                                 and **at least one check** must exist to let it through; on success the pending is cleared and it enters history
        edit_revert(why)                      → why is required; rolls back to the object state at begin;
                                                 **free of budget but capped** (see _txn_revert_cap: cap = max(2, history steps)),
                                                 and guards against "change once, undo once" dithering (consecutive reverts of the same label are refused outright)
        edit_status()                         → the current pending (label/targets/start time/check count) + accept/undo counts + remaining allowance
      **Only one pending is allowed at a time**: when one already exists, edit_begin returns ok:false and makes the caller accept or revert first.
      Relation to file-level snapshots: edit_begin **does not** take a .blend snapshot (MB-scale write cost on large scenes); but it hints in the response —
      **topology-changing edits (boolean / join / face deletion / apply_transform) must first leave a file-level rollback point with t_snapshot(...)**,
      because object-level snapshots cannot restore topology.

Usage (works in the GUI or headless):
    K.dsh_txn_api["snapshot"]("before_join")
    K.dsh_txn_api["mark"]("iter7", ["Cube", "Wheel_L"])
    ... make changes ...
    K.dsh_txn_api["revert"]("iter7")     # quickly back to the state at mark time
    K.dsh_txn_api["restore"]("before_join")                  # default: load the snapshot and write it back to the original file (undoable)
    K.dsh_txn_api["restore"]("before_join", into="snapshot") # just a look: non-destructive, the original file is untouched

    # pending edits (#12): change → review → accept / undo
    K.dsh_txn_api["edit_begin"]("tenon_12mm", "edit", ["Backrest"])
    ... change ...
    K.dsh_txn_api["edit_check"]("render", {"view": "iso", "note": "the tenon went in"})
    K.dsh_txn_api["edit_accept"]("iso view compared to the target: the tenon goes in 12mm, direction correct, no detachment")
"""
import bpy
import json
import os
import shutil
import time

TXN_VERSION = 4

# Boundary of object-level rollback (copied verbatim to the caller so nobody thinks revert can restore topology)
_TXN_BOUNDARY = ("object-level snapshot/rollback covers only transform / material slots / visibility / modifier toggles; "
            "it does not cover topology (boolean / join / face deletion / apply_transform), UVs, or vertex positions — "
            "for that kind of change leave a file-level rollback point with t_snapshot(...) first")
# Lower bound of the undo allowance: a new session must at least be able to "change once → undo once" (upstream = Math.max(2, maxRefineSteps))
_TXN_REVERT_FLOOR = 2
# Known values of the review kind (non-standard kinds are still recorded, but get a "non-standard" note back)
_TXN_CHECK_KINDS = ("audit", "qc", "measure", "render", "read", "compare", "other")


import sys as _sys_kit
_KIT = getattr(_sys_kit.modules.get("dsh_rt_kernel"), "dsh_kit", None)
if _KIT is None:
    raise RuntimeError("txn needs the shared kernel K.dsh_kit (injected by KERNEL_BOOTSTRAP)")


def _txn_j(o):
    return json.dumps(o, ensure_ascii=False, default=str)


def _txn_kernel():
    import sys
    return sys.modules.get("dsh_rt_kernel")


def _txn_store():
    K = _txn_kernel()
    if K is None:
        raise RuntimeError("the persistent kernel K is required (go through the blender_rt_* channel)")
    if not hasattr(K, "dsh_txn"):
        K.dsh_txn = {"snapshots": {}, "marks": {}}
    st = K.dsh_txn
    # v3 keys are filled in with setdefault — K survives across calls/reloads, so an old session's store may still have the v2 shape
    st.setdefault("snapshots", {})
    st.setdefault("marks", {})
    st.setdefault("pending", None)        # the current pending edit (at most one at a time)
    st.setdefault("edits", [])            # settled edit history (one entry each for accepted / reverted)
    st.setdefault("edit_steps", 0)        # cumulative number of edit_begin calls — the single definition of "history steps"
    st.setdefault("accepted", 0)
    st.setdefault("reverted", 0)
    st.setdefault("last_action", None)    # {"kind": "accept"|"revert", "label": ...} → dither criterion
    return st


def _txn_out_dir():
    K = _txn_kernel()
    d = getattr(K, "out_dir", None) or os.path.join(os.path.expanduser("~"), "dsh_out")
    return d


def _txn_now():
    return time.strftime("%Y-%m-%d %H:%M:%S")


# ---------------------------------------------------------------- file level

def _txn_snap_dir():
    return os.path.join(_txn_out_dir(), "snapshots")


def _txn_under(path, d):
    """Whether path falls inside directory d — the restore write-back target must not be the plugin's own snapshot directory."""
    try:
        p = os.path.normcase(os.path.abspath(str(path)))
        dd = os.path.normcase(os.path.abspath(str(d)))
        return p == dd or p.startswith(dd + os.sep)
    except Exception:
        return False


def _txn_same_path(a, b):
    try:
        return os.path.normcase(os.path.abspath(str(a))) == os.path.normcase(os.path.abspath(str(b)))
    except Exception:
        return False


def _txn_reg_snap(label, path, note, auto=False, ms=None):
    """Register an already-written .blend in the snapshot list (list/prune/restore all recognise it)."""
    st = _txn_store()
    rec = {"label": label, "path": path,
           "bytes": os.path.getsize(path) if os.path.isfile(path) else None,
           "ms": ms, "objects": len(bpy.data.objects), "note": str(note), "t": _txn_now(),
           "auto": bool(auto), "filepath": str(bpy.data.filepath or "")}
    st["snapshots"][label] = rec
    return rec


def _txn_backup_now(label, note):
    """Store **the current session state** as a snapshot (the undo point before restore)."""
    d = _txn_snap_dir()
    os.makedirs(d, exist_ok=True)
    path = os.path.join(d, label + ".blend")
    t0 = time.perf_counter()
    bpy.ops.wm.save_as_mainfile(filepath=path, copy=True)
    return _txn_reg_snap(label, path, note, auto=True, ms=int((time.perf_counter() - t0) * 1000))


def _txn_backup_file(src, label, note):
    """Save **the original file on disk** as a copy (when the session is dirty it differs from the in-memory state, so it must be backed up before an overwrite)."""
    d = _txn_snap_dir()
    os.makedirs(d, exist_ok=True)
    path = os.path.join(d, label + ".blend")
    shutil.copy2(src, path)
    return _txn_reg_snap(label, path, note, auto=True, ms=0)


def t_snapshot(label=None, note=""):
    st = _txn_store()
    d = _txn_snap_dir()
    os.makedirs(d, exist_ok=True)
    name = str(label) if label else time.strftime("snap_%Y%m%d_%H%M%S")
    path = os.path.join(d, name + ".blend")
    t0 = time.perf_counter()
    try:
        bpy.ops.wm.save_as_mainfile(filepath=path, copy=True)
    except Exception as e:
        return _txn_j({"ok": False, "error": "%s: %s" % (type(e).__name__, e), "path": path})
    ms = int((time.perf_counter() - t0) * 1000)
    rec = {"label": name, "path": path, "bytes": os.path.getsize(path) if os.path.isfile(path) else None,
           "ms": ms, "objects": len(bpy.data.objects), "note": str(note), "t": _txn_now(),
           # v4: record "the filepath at snapshot time" — restore uses it to put the session back on the original file (recognisable even after another file was opened)
           "filepath": str(bpy.data.filepath or ""), "unsaved": (not bpy.data.filepath)}
    st["snapshots"][name] = rec
    return _txn_j({"ok": True, "snapshot": rec, "total": len(st["snapshots"])})


_TXN_INTO = ("auto", "original", "snapshot")


def _txn_restore_target(rec, before, snap_dir):
    """Write-back target: prefer the file the snapshot came from, else the session's current file; if both are inside the snapshot directory → no target.

    The order matters: the recorded origin is checked first. The user may have opened a **different** project before restoring —
    writing the snapshot content into the "current file" then would destroy another project, so writing back to the origin is correct.
    """
    for cand, src in ((str(rec.get("filepath") or ""), "snapshot_filepath"),
                      (str(before or ""), "session_filepath")):
        if cand and not _txn_under(cand, snap_dir):
            return cand, src
    return "", ""


def t_restore(label, into="auto", backup=True):
    """Load a snapshot. into="auto" (default) returns to the file the snapshot came from after loading; "snapshot" only loads without writing the original.

    v4 fixes the filepath semantics: in the old version, after open_mainfile the session was attached to snapshots/<label>.blend,
    so the user's first save wrote into the snapshot directory (even though the original file was still there). See the "File level" section at the top of the file.
    """
    st = _txn_store()
    rec = st["snapshots"].get(str(label))
    if not rec:
        return _txn_j({"ok": False, "error": "no such snapshot: %s" % label, "have": sorted(st["snapshots"])})
    path = rec["path"]
    if not os.path.isfile(path):
        return _txn_j({"ok": False, "error": "snapshot file does not exist: %s" % path})

    into = str(into or "auto").strip().lower()
    if into not in _TXN_INTO:
        return _txn_j({"ok": False, "error": "into accepts only auto / original / snapshot", "given": into,
                       "into_allowed": list(_TXN_INTO)})

    before = str(bpy.data.filepath or "")
    dirty = bool(getattr(bpy.data, "is_dirty", False))
    snap_dir = _txn_snap_dir()
    target, target_src = ("", "") if into == "snapshot" else _txn_restore_target(rec, before, snap_dir)
    if into == "original" and not target:
        return _txn_j({"ok": False,
                       "error": "no writable original file (neither the snapshot record nor the session has a non-snapshot path); to just look, use into='snapshot'",
                       "filepath_before": before, "snapshot_filepath": str(rec.get("filepath") or "")})

    # ① safety net: restore discards the current unsaved state — leave an undo point first
    bk, bk_err, disk_bk, disk_err = None, None, None, None
    if backup:
        stamp = time.strftime("%Y%m%d_%H%M%S")
        try:
            bk = _txn_backup_now("_pre_restore_%s_%s" % (str(label), stamp),
                                 "automatic backup before restore '%s' (the state before the session was replaced)" % label)
        except Exception as e:
            bk_err = "%s: %s" % (type(e).__name__, e)
        # session dirty ⇒ in-memory state ≠ the original file on disk; if the original file is to be overwritten, its on-disk copy must be backed up too
        if target and dirty and os.path.isfile(target):
            try:
                disk_bk = _txn_backup_file(target, "_pre_restore_file_%s_%s" % (str(label), stamp),
                                           "on-disk copy of the original file (before restore overwrites it)")
            except Exception as e:
                disk_err = "%s: %s" % (type(e).__name__, e)

    # ② load the snapshot
    t0 = time.perf_counter()
    try:
        bpy.ops.wm.open_mainfile(filepath=path)
    except Exception as e:
        return _txn_j({"ok": False, "error": "%s: %s" % (type(e).__name__, e), "path": path,
                       "filepath_before": before, "backup": bk, "backup_error": bk_err})
    loaded_ms = int((time.perf_counter() - t0) * 1000)

    # ③ put the session back on the original file (skipped for into="snapshot", which only spells out "where a save would land")
    wrote, write_err = False, None
    if target:
        try:
            bpy.ops.wm.save_as_mainfile(filepath=target)
            wrote = True
        except Exception as e:
            write_err = "%s: %s" % (type(e).__name__, e)
    after = str(bpy.data.filepath or "")
    note = []
    if wrote:
        note.append("the snapshot was restored and the session was put back on the original file %s (later saves land here again, not in the snapshot directory)" % target)
        if target_src == "snapshot_filepath" and before and not _txn_same_path(before, target):
            note.append("note: before the restore the session was attached to %s, and it has been switched back to the file the snapshot came from" % before)
        if bk is None:
            note.append("⚠ could not keep a pre-restore backup (%s) — unsaved changes from before the snapshot are lost" % (bk_err or "backup=False"))
        else:
            note.append("the state before restore was backed up as snapshot %s (can be restored back)" % bk.get("label"))
        if disk_bk:
            note.append("on-disk copy of the original file: %s" % disk_bk.get("label"))
    else:
        note.append("the snapshot was loaded, but there is **no** writable original file — the current session is attached to the snapshot file, "
                    "so a save now writes into the snapshot directory (%s); to land it in your own project, save explicitly" % (after or path))
        if bk is not None:
            note.append("the state before restore was backed up as snapshot %s" % bk.get("label"))

    out = {"ok": True, "restored": rec, "ms": loaded_ms, "objects": len(bpy.data.objects),
           "into": into, "wrote_to_original": wrote, "target": (target or None),
           "target_source": (target_src or None), "filepath_before": before,
           "filepath": after, "next_save_goes_to": after,
           "backup": bk, "backup_error": bk_err, "on_disk_backup": disk_bk, "on_disk_backup_error": disk_err,
           "warning": " ".join(note)}
    if write_err:
        out["ok"] = False
        out["error"] = "the snapshot was loaded, but writing it back to the original file failed: %s (the session is still on the snapshot path %s)" % (write_err, after)
    return _txn_j(out)


def t_list():
    st = _txn_store()
    snaps = sorted(st["snapshots"].values(), key=lambda r: r.get("t", ""))
    return _txn_j({"ok": True, "snapshots": snaps, "marks": sorted(st["marks"]),
               "out_dir": _txn_out_dir(),
               "snapshot_dir": os.path.join(_txn_out_dir(), "snapshots")})


def t_prune(keep=5):
    st = _txn_store()
    keep = max(1, int(keep or 5))
    snaps = sorted(st["snapshots"].values(), key=lambda r: r.get("t", ""))
    removed = []
    for rec in snaps[:-keep]:
        try:
            if os.path.isfile(rec["path"]):
                os.remove(rec["path"])
            removed.append(rec["label"])
        except Exception as e:
            pass
        st["snapshots"].pop(rec["label"], None)
    return _txn_j({"ok": True, "removed": removed, "kept": sorted(st["snapshots"])})


# ---------------------------------------------------------------- object level

def _txn_snap_obj(ob):
    d = {
        "name": ob.name,
        "loc": [round(v, 6) for v in ob.location],
        "rot": [round(v, 6) for v in ob.rotation_euler],
        "scale": [round(v, 6) for v in ob.scale],
        "hide_viewport": bool(ob.hide_viewport),
        "hide_render": bool(ob.hide_render),
        "hide_get": bool(ob.hide_get()) if hasattr(ob, "hide_get") else None,
        "materials": [m.name if m else None for m in ob.data.materials] if getattr(ob, "data", None) and hasattr(ob.data, "materials") else None,
        "modifiers": [{"name": m.name, "type": m.type, "show_viewport": bool(m.show_viewport),
                       "show_render": bool(m.show_render)} for m in ob.modifiers],
    }
    if ob.type == "MESH" and ob.data is not None:
        d["verts"] = len(ob.data.vertices)
        d["polys"] = len(ob.data.polygons)
    return d


def t_mark(label, objects=None):
    st = _txn_store()
    name = str(label)
    if objects:
        obs = [bpy.data.objects.get(str(n)) for n in objects]
        obs = [o for o in obs if o is not None]
    else:
        obs = [o for o in bpy.data.objects]
    rec = {"label": name, "t": _txn_now(), "objects": {o.name: _txn_snap_obj(o) for o in obs},
           "count": len(obs), "scene": bpy.context.scene.name if bpy.context.scene else None}
    st["marks"][name] = rec
    return _txn_j({"ok": True, "mark": name, "objects": len(obs), "note": "object level: only transform/materials/visibility/modifier toggles; no topology changes"})


def _txn_restore_objects(objects_snap):
    """Write {object name: _txn_snap_obj record} back in place → (changed, missing, blocked).

    Boundary: only transform / material slots / visibility / modifier toggles are written back; **objects whose topology changed are skipped and reported**
    (a mismatched vertex count means the topology changed, and forcing the write would misalign the material slots). t_revert and edit_revert share this implementation.
    """
    changed, missing, blocked = [], [], []
    for oname, snap in (objects_snap or {}).items():
        ob = bpy.data.objects.get(oname)
        if ob is None:
            missing.append(oname)
            continue
        if snap.get("verts") is not None and ob.type == "MESH" and ob.data is not None:
            if len(ob.data.vertices) != snap["verts"]:
                blocked.append({"name": oname, "why": "topology has changed (vertex count %d → %d)" % (snap["verts"], len(ob.data.vertices))})
                continue
        before = _txn_snap_obj(ob)
        try:
            ob.location = snap["loc"]
            ob.rotation_euler = snap["rot"]
            ob.scale = snap["scale"]
            ob.hide_viewport = snap["hide_viewport"]
            ob.hide_render = snap["hide_render"]
            if snap.get("hide_get") is not None and hasattr(ob, "hide_set"):
                ob.hide_set(snap["hide_get"])
            if snap.get("materials") is not None and getattr(ob, "data", None) is not None and hasattr(ob.data, "materials"):
                mats = ob.data.materials
                for i, mname in enumerate(snap["materials"]):
                    m = bpy.data.materials.get(mname) if mname else None
                    if i < len(mats):
                        mats[i] = m
                    else:
                        mats.append(m)          # a slot had been deleted → put it back in place (otherwise "the rollback is incomplete")
                while len(mats) > len(snap["materials"]):
                    try:
                        mats.pop(index=len(mats) - 1)   # extra slots (added while editing) are removed too
                    except Exception:
                        break
            for mi, msnap in enumerate(snap.get("modifiers") or []):
                if mi < len(ob.modifiers):
                    ob.modifiers[mi].show_viewport = msnap["show_viewport"]
                    ob.modifiers[mi].show_render = msnap["show_render"]
        except Exception as e:
            blocked.append({"name": oname, "why": "%s: %s" % (type(e).__name__, e)})
            continue
        after = _txn_snap_obj(ob)
        if json.dumps(before, sort_keys=True) != json.dumps(after, sort_keys=True):
            changed.append(oname)
    return changed, missing, blocked


def t_revert(label, strict=False):
    st = _txn_store()
    rec = st["marks"].get(str(label))
    if not rec:
        return _txn_j({"ok": False, "error": "no such mark: %s" % label, "have": sorted(st["marks"])})
    changed, missing, blocked = _txn_restore_objects(rec["objects"])
    bpy.context.view_layer.update()
    return _txn_j({"ok": True, "reverted": str(label), "changed": changed, "changed_count": len(changed),
               "missing_objects": missing, "blocked": blocked,
               "boundary": _TXN_BOUNDARY})


def t_marks():
    st = _txn_store()
    return _txn_j({"ok": True, "marks": [{"label": k, "objects": v["count"], "t": v["t"]} for k, v in st["marks"].items()]})


def t_drop(label):
    st = _txn_store()
    hit = st["marks"].pop(str(label), None)
    return _txn_j({"ok": True, "dropped": bool(hit), "label": str(label), "remaining": sorted(st["marks"])})


# ---------------------------------------------------------------- pending edits (v0.9.0 / #12)

def _txn_revert_cap(steps, explicit=None):
    """Cap on the undo allowance — the cap in "free of budget but capped" (its definition is fixed here and returned with every response).

        cap = the explicit cap argument (preferred when given and >= 1)
              otherwise max(_TXN_REVERT_FLOOR, the number of edit_begin history steps)

    Why this way: upstream edit-transaction.ts is `Math.max(2, maxRefineSteps)` — the more work done, the more rework is allowed;
    the floor of 2 guarantees a **new session** can at least "change once → undo once" (otherwise the very first undo is impossible and the protocol is worthless);
    the cap grows with the step count instead of being a fixed constant, so a long session never permanently loses the right to undo because of one early dither.
    The dither guard (consecutive revert of the same label) is a separate gate and does not consume this allowance.
    """
    if explicit is not None:
        try:
            return max(1, int(explicit))
        except Exception:
            pass
    try:
        return max(_TXN_REVERT_FLOOR, int(steps or 0))
    except Exception:
        return _TXN_REVERT_FLOOR


def _txn_pending_view(st):
    """Readable summary of the pending (reused by edit_status / refusal messages)."""
    p = st.get("pending")
    if not p:
        return None
    return {"label": p["label"], "op": p["op"], "targets": list(p["targets"]), "objects": p["count"],
            "started": p["t"], "age_ms": int((time.perf_counter() - p["t0"]) * 1000),
            "checks": len(p["checks"]), "check_kinds": [c["kind"] for c in p["checks"]],
            "note": p["note"], "scene": p["scene"]}


def t_edit_begin(label, op="edit", targets=None, note=""):
    """Start one pending edit: record a transform/materials/visibility snapshot of the target objects and attach a pending (only one at a time).

    It does **not** take a .blend snapshot (MB-scale cost on large scenes) — for a file-level rollback point call t_snapshot();
    topology-changing edits (boolean / join / face deletion / apply_transform) **must** go through t_snapshot, object level cannot restore topology.
    """
    st = _txn_store()
    if st.get("pending"):
        p = st["pending"]
        return _txn_j({"ok": False, "error": "a pending edit already exists (label=%s) — accept or revert it first, only one is allowed at a time" % p.get("label"),
                   "pending": _txn_pending_view(st), "hint": "edit_status() shows the current pending"})
    name = str(label).strip() if label is not None else ""
    if not name:
        return _txn_j({"ok": False, "error": "label is required (an empty label cannot be matched in history)"})
    missing = []
    if targets:
        want = [str(x) for x in (targets if isinstance(targets, (list, tuple)) else [targets])]
        got = []
        for n in want:
            o = bpy.data.objects.get(n)
            if o is None:
                missing.append(n)
            else:
                got.append(o)
    else:
        got = [o for o in bpy.context.scene.objects]
    if not got:
        return _txn_j({"ok": False, "error": "no usable target objects (none of the targets exist, or the scene has no objects)",
                   "targets": targets, "missing_targets": missing})
    rec = {"label": name, "op": str(op or "edit"), "note": str(note), "t": _txn_now(), "t0": time.perf_counter(),
           "targets": [o.name for o in got], "objects": {o.name: _txn_snap_obj(o) for o in got}, "count": len(got),
           "checks": [], "scene": bpy.context.scene.name if bpy.context.scene else None}
    st["pending"] = rec
    st["edit_steps"] = int(st.get("edit_steps", 0)) + 1
    return _txn_j({"ok": True, "pending": True, "label": name, "op": rec["op"], "objects": len(got),
               "targets": rec["targets"], "missing_targets": missing, "checks": 0,
               "steps": st["edit_steps"], "revert_cap": _txn_revert_cap(st["edit_steps"]),
               "hint": "after editing, call edit_check(kind='audit'|'qc'|'measure') first, then edit_accept(verified='...')",
               "hint_topology": "for a file-level rollback point call t_snapshot(label) first; topology-changing edits (boolean/join/face deletion) cannot be undone at object level",
               "boundary": _TXN_BOUNDARY})


def t_edit_check(kind, result=None, note=""):
    """Register one post-edit review (kind = audit / qc / measure / render / read / compare / other).

    edit_accept requires **at least one** check — that is the gate for "compile and look before accepting".
    """
    st = _txn_store()
    p = st.get("pending")
    if not p:
        return _txn_j({"ok": False, "error": "no pending edit — call edit_begin(label, targets=[...]) first"})
    k = str(kind).strip() if kind is not None else ""
    if not k:
        return _txn_j({"ok": False, "error": "kind is required (audit / qc / measure / render ...)", "known": list(_TXN_CHECK_KINDS)})
    if isinstance(result, str):
        try:
            result = json.loads(result)
        except Exception:
            pass
    p["checks"].append({"seq": len(p["checks"]) + 1, "kind": k, "result": result, "note": str(note), "t": _txn_now()})
    out = {"ok": True, "label": p["label"], "checks": len(p["checks"]), "kinds": [c["kind"] for c in p["checks"]]}
    if k not in _TXN_CHECK_KINDS:
        out["unknown_kind"] = "non-standard kind=%s (still recorded; the standard values are %s)" % (k, "/".join(_TXN_CHECK_KINDS))
    return _txn_j(out)


def t_edit_accept(verified):
    """Accept the pending edit: `verified` is required (one line saying "what was looked at, what was confirmed"), and a check record must already exist.

    An empty string / pure whitespace is refused outright; no edit_check record is refused ("not reviewed yet, run audit/qc first").
    """
    st = _txn_store()
    p = st.get("pending")
    if not p:
        return _txn_j({"ok": False, "error": "no pending edit to accept — call edit_begin + make changes first"})
    v = str(verified).strip() if verified is not None else ""
    if not v:
        return _txn_j({"ok": False, "error": "verified is required: one line saying what was looked at and what was confirmed (an empty string is not accepted)",
                   "want": "e.g. verified='iso view compared to the target: the tenon goes in 12mm, direction correct, no detachment'", "label": p["label"]})
    if not p["checks"]:
        return _txn_j({"ok": False, "error": "not reviewed yet, run audit/qc first — an edit must be verified before it is accepted (at least one edit_check(kind=...))",
                   "label": p["label"], "checks": 0,
                   "hint": "call edit_check('audit', result={...}) or edit_check('qc', result={...}), then edit_accept"})
    ms = int((time.perf_counter() - p["t0"]) * 1000)
    st["accepted"] = int(st.get("accepted", 0)) + 1
    st["edits"].append({"label": p["label"], "op": p["op"], "outcome": "accepted", "t_begin": p["t"], "t_end": _txn_now(),
                        "ms": ms, "targets": list(p["targets"]), "checks": [c["kind"] for c in p["checks"]],
                        "verified": v})
    del st["edits"][:-200]
    st["pending"] = None
    st["last_action"] = {"kind": "accept", "label": p["label"], "t": _txn_now()}
    limit = _txn_revert_cap(st.get("edit_steps"))
    used = int(st.get("reverted", 0))
    return _txn_j({"ok": True, "accepted": st["accepted"], "label": p["label"], "verified": v, "checks": len(p["checks"]),
               "check_kinds": [c["kind"] for c in p["checks"]], "ms": ms, "pending": False,
               "reverts_left": max(0, limit - used), "revert_cap": limit,
               "next": "next cycle: make another change and call edit_begin; only accept after you have really looked"})


def t_edit_revert(why, cap=None):
    """Undo the pending edit: roll back to the object state at edit_begin. `why` is required; free of budget but capped, plus a dither guard.

    For the cap definition see _txn_revert_cap (default max(2, edit_begin history steps); cap= overrides it explicitly).
    Dither guard: if the previous action was also a revert with the same label → refuse ("don't dither between change and undo; get the measurement right first").
    Boundary is the same as object level: topology/UV/vertex changes cannot be undone (objects whose topology changed are skipped and reported); that kind of change needs t_snapshot.
    """
    st = _txn_store()
    p = st.get("pending")
    if not p:
        return _txn_j({"ok": False, "error": "no pending edit to undo — call edit_begin + make changes first"})
    w = str(why).strip() if why is not None else ""
    if not w:
        return _txn_j({"ok": False, "error": "why is required: one line saying what is wrong in what the review/render showed (an empty string is not accepted)",
                   "want": "e.g. why='in the iso view the tenon is 4mm short: direction is right but it does not reach the bottom → recompute delta and edit again'", "label": p["label"]})
    la = st.get("last_action") or {}
    if la.get("kind") == "revert" and str(la.get("label")) == str(p["label"]):
        return _txn_j({"ok": False, "code": "dither_guard",
                   "error": "dither guard: the previous action was already revert(%s) and this time the same label is reverted again — don't dither between change and undo, get the measurement right first" % p["label"],
                   "label": p["label"], "last_action": la,
                   "hint": "measure first (get the real deviation), then edit once more; or use a different label to signal a different editing intent"})
    limit = _txn_revert_cap(st.get("edit_steps"), cap)
    used = int(st.get("reverted", 0))
    if used >= limit:
        return _txn_j({"ok": False, "code": "revert_budget_spent",
                   "error": "undo allowance exhausted (%d/%d) — if this edit is a net improvement, edit_accept it; don't dither between change and undo" % (used, limit),
                   "label": p["label"], "reverts_left": 0, "revert_cap": limit,
                   "budget_rule": "undo allowance = max(%d, edit_begin history steps); cap= overrides it explicitly" % _TXN_REVERT_FLOOR})
    changed, missing, blocked = _txn_restore_objects(p["objects"])
    bpy.context.view_layer.update()
    ms = int((time.perf_counter() - p["t0"]) * 1000)
    st["reverted"] = used + 1
    st["edits"].append({"label": p["label"], "op": p["op"], "outcome": "reverted", "t_begin": p["t"], "t_end": _txn_now(),
                        "ms": ms, "targets": list(p["targets"]), "checks": [c["kind"] for c in p["checks"]],
                        "why": w, "changed_count": len(changed), "blocked": blocked})
    del st["edits"][:-200]
    st["pending"] = None
    st["last_action"] = {"kind": "revert", "label": p["label"], "t": _txn_now()}
    return _txn_j({"ok": True, "reverted": p["label"], "why": w, "changed": changed, "changed_count": len(changed),
               "missing_objects": missing, "blocked": blocked, "ms": ms, "pending": False,
               "reverts_left": max(0, limit - st["reverted"]), "revert_cap": limit,
               "amend": "this undo does not spend edit budget: get the measurement right now and edit once more (you may use a label other than the same one)",
               "boundary": _TXN_BOUNDARY})


def t_edit_status():
    """The current pending (label/targets/start time/check count) + accept/undo counts + remaining undo allowance + boundary reminder."""
    st = _txn_store()
    steps = int(st.get("edit_steps", 0))
    used = int(st.get("reverted", 0))
    limit = _txn_revert_cap(steps)
    hist = []
    for e in (st.get("edits") or [])[-5:]:
        hist.append({"label": e.get("label"), "outcome": e.get("outcome"), "t_end": e.get("t_end"),
                     "checks": e.get("checks"), "ms": e.get("ms")})
    return _txn_j({"ok": True, "version": TXN_VERSION, "pending": _txn_pending_view(st), "has_pending": bool(st.get("pending")),
               "accepted": int(st.get("accepted", 0)), "reverted": used, "steps": steps,
               "revert_cap": limit, "reverts_left": max(0, limit - used),
               "budget_rule": "undo allowance = max(%d, edit_begin history steps) (free of budget but capped); cap= overrides it explicitly" % _TXN_REVERT_FLOOR,
               "dither_guard": "if the previous action was a revert of the same label, this revert is refused (guards against dithering between change and undo)",
               "accept_gate": "edit_accept requires a non-empty verified plus at least one edit_check record",
               "topology_warning": "when the edit includes topology changes (boolean / join / face deletion / apply_transform): call t_snapshot(label) first — object-level snapshots cannot restore topology, and such objects are skipped and reported in revert",
               "history": hist, "boundary": _TXN_BOUNDARY})


def t_help():
    return _txn_j({
        "version": TXN_VERSION,
        "file_level": {"snapshot": "snapshot(label=None, note='') → saves <out_dir>/snapshots/<label>.blend (copy=True, the current filepath is untouched) and records the filepath at that time",
                       "restore": "restore(label, into='auto', backup=True) → loads the snapshot. "
                                  "into='auto' (default) returns to the file the snapshot came from after loading (restored into the original file, so saves no longer fall into the snapshot directory); "
                                  "into='snapshot' is non-destructive: just a look, not a single byte written to the original file; "
                                  "into='original' requires a writable target, otherwise ok:false. "
                                  "backup=True first leaves a pre_restore snapshot before restoring (and an extra on-disk copy when the session is dirty and the original file is to be overwritten)",
                       "list": "list() → snapshot + mark list", "prune": "prune(keep=5) → keeps only the N most recent snapshots (automatic backups count as ordinary snapshots and can be pruned)"},
        "object_level": {"mark": "mark(label, objects=None) → records transform/materials/visibility/modifier toggles",
                         "revert": "revert(label, strict=False) → writes back in place; objects whose topology changed are skipped and reported",
                         "marks": "marks() → list the marks", "drop": "drop(label) → delete a mark"},
        "pending_edit": {"edit_begin": "edit_begin(label, op='edit', targets=None, note='') → attaches a pending (only one at a time; refused outright when one already exists)",
                         "edit_check": "edit_check(kind, result=None, note='') → records a review (kind=audit/qc/measure/render...); at least one before accept",
                         "edit_accept": "edit_accept(verified) → verified is required and must be non-empty; refused without a check record; on success returns the accepted count",
                         "edit_revert": "edit_revert(why, cap=None) → why is required; rolls back to the state at begin; free of budget but capped (default max(2, history steps)) + dither guard on consecutive reverts of the same label",
                         "edit_status": "edit_status() → pending (label/targets/start time/check count) + accepted/reverted + remaining undo allowance"},
        "boundary": "object level does not include topology/UV/vertex changes; file level is a full rollback but costs disk writes. "
                    "Pending-edit protocol: edit_begin does not take a .blend snapshot — topology-changing edits (boolean/join/face deletion/apply_transform) must call t_snapshot() first",
        "usage": "K.dsh_txn_api[...]; the blender_rt_txn(op=...) tool works too. Typical: edit_begin → edit → edit_check('qc', {...}) → edit_accept('iso comparison: direction correct, goes in 12mm')",
    })


def t_dispatch(op, args=None):
    """Unified entry point: the tool side sends {op, args}"""
    if isinstance(args, str):
        try:
            args = json.loads(args) if args.strip() else {}
        except Exception:
            args = {}
    kw = {}
    for k, v in (args or {}).items():
        if k == "args" and isinstance(v, dict):
            kw.update(v)
        else:
            kw[k] = v
    fn = t_ops().get(str(op))
    if fn is None:
        return _txn_j({"ok": False, "error": "unknown txn op", "op": op, "ops": sorted(t_ops())})
    try:
        return fn(**kw)
    except TypeError as e:
        return _txn_j({"ok": False, "error": "parameters do not match: %s" % e, "op": op, "given": sorted(kw), "sig_hint": t_help()})


def t_ops():
    return {"snapshot": t_snapshot, "restore": t_restore, "list": t_list, "prune": t_prune,
            "mark": t_mark, "revert": t_revert, "marks": t_marks, "drop": t_drop, "help": t_help,
            "edit_begin": t_edit_begin, "edit_check": t_edit_check, "edit_accept": t_edit_accept,
            "edit_revert": t_edit_revert, "edit_status": t_edit_status}


import sys as _sys
_txn_K = _sys.modules.get("dsh_rt_kernel")
def t_selftest():
    # transaction self-test: mark -> really change the object -> revert must restore the transform
    import json

    def _d(x):
        return json.loads(x) if isinstance(x, str) else x

    import bpy
    import bmesh as _bm
    ev = {}
    nm = "__dsh_tx_cube"
    lb = "__dsh_selftest_mark"
    try:
        me = bpy.data.meshes.new(nm)
        ob = bpy.data.objects.new(nm, me)
        bpy.context.scene.collection.objects.link(ob)
        bm = _bm.new()
        _bm.ops.create_cube(bm, size=1.0)
        bm.to_mesh(me)
        bm.free()
        ob.location = (0.0, 0.0, 0.0)
        _d(t_mark(lb, [nm]))
        ob.location = (5.0, 5.0, 5.0)
        try:
            bpy.context.view_layer.update()
        except Exception:
            pass
        ev["changed"] = abs(bpy.data.objects[nm].location[0] - 5.0) < 1e-4
        r = _d(t_revert(lb))
        ev["revert_ok"] = isinstance(r, dict) and r.get("ok") is not False
        try:
            bpy.context.view_layer.update()
        except Exception:
            pass
        loc = bpy.data.objects[nm].location
        ev["restored"] = abs(loc[0]) < 1e-4 and abs(loc[2]) < 1e-4
        ev["marks_listable"] = isinstance(_d(t_list()), dict)
        return _KIT.j({"ok": all(x is True for x in ev.values()), "evidence": ev, "loc": [round(float(q), 3) for q in loc]})
    except Exception as e:
        return _KIT.j({"ok": False, "evidence": ev, "error": "%s: %s" % (type(e).__name__, str(e)[:200])})
    finally:
        o = bpy.data.objects.get(nm)
        if o is not None:
            me2 = o.data
            bpy.data.objects.remove(o, do_unlink=True)
            if me2 is not None and me2.users == 0:
                bpy.data.meshes.remove(me2, do_unlink=True)



if _txn_K is not None:
    _txn_K.dsh_txn_api = _KIT.Api({"version": TXN_VERSION, "dispatch": _KIT.wrap_dispatch(t_dispatch, {"selftest": t_selftest}), "snapshot": t_snapshot, "restore": t_restore,
                      "list": t_list, "prune": t_prune, "mark": t_mark, "revert": t_revert,
                      "marks": t_marks, "drop": t_drop, "help": t_help,
                      "edit_begin": t_edit_begin, "edit_check": t_edit_check, "edit_accept": t_edit_accept,
                      "edit_revert": t_edit_revert, "edit_status": t_edit_status,
        "selftest": t_selftest})

# ---- v0.9.1 (93-B1/B2): make the API callable (swap in a dict-subclass instance that returns parsed objects) ----
# Background: K.dsh_x_api used to be a plain dict → the in-process api(args) raised TypeError: 'dict' object is not callable;
# and dispatch returned a JSON string, so the caller still had to json.loads it itself.
# Now: api("op", {…}) or api({…}) → dict; api["dispatch"](op, json_str) still returns str (the engine contract is unchanged).
# Note: dict is a static type and assigning __class__ on an existing instance fails (TypeError in practice), so a new instance is used instead.
_DshApi = _KIT.Api  # shared kernel (the trailing registration line needs no change)
import sys as _sys_api
_K_api = _sys_api.modules.get("dsh_rt_kernel")
if _K_api is not None and isinstance(getattr(_K_api, "dsh_txn_api", None), dict) \
        and not isinstance(getattr(_K_api, "dsh_txn_api", None), _DshApi):
    _K_api.dsh_txn_api = _DshApi(_K_api.dsh_txn_api)
