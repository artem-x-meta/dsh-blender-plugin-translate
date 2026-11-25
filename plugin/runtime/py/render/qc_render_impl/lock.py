# -*- coding: utf-8 -*-
"""Split from qc_render.py; behavior preserved by the facade."""
from .common import *  # noqa: F401,F403

def _lock_holder_default():
    """Default holder: `DSH_SESSION#<pid>` → `DSH_RUN_ID#<pid>` → `pid-<pid>`.

    Why the pid (settled in v0.9.1): **launching several headless processes concurrently** in one DSH session is a common
    pattern (batch / multiple members), and the session name alone gives them the same name → they wrongly release each other's locks. With the pid they stay unique even inside one session.
    """
    h = os.environ.get("DSH_SESSION") or os.environ.get("DSH_RUN_ID")
    return ("%s#%d" % (h, os.getpid())) if h else ("pid-%d" % os.getpid())


def _lock_base(override=None):
    return str(override) if override else _work_dir()


def _lock_path(base=None):
    """Lock file path: <base>/locks/render.lock (base defaults to _work_dir(); WSL paths are converted to the Windows side automatically)."""
    return _win(os.path.join(_lock_base(base), "locks", "render.lock"))


def _lock_read(path):
    """Read the lock file → (info|None, err).

    err == "missing" means the lock does not exist (callers treat it as "nobody holds it", not an error);
    when it cannot be parsed, return {"_unparsable": True, "_mtime": ..., "_raw": ...} —— do not guess the holder, judge age from mtime only.
    """
    try:
        with open(path, "r", encoding="utf-8") as f:
            raw = f.read()
    except FileNotFoundError:
        return None, "missing"
    except Exception as e:
        return None, "%s: %s" % (type(e).__name__, str(e)[:120])
    try:
        info = json.loads(raw)
        if not isinstance(info, dict):
            raise ValueError("not a JSON object")
        return info, None
    except Exception as e:
        mt = None
        try:
            mt = float(os.path.getmtime(path))
        except Exception:
            pass
        return {"_unparsable": True, "_mtime": mt, "_raw": str(raw)[:200]}, "parse failed: %s" % str(e)[:120]


def _lock_age(info, path):
    """Lock age in seconds + the source of the criterion ("acquired_at" | "mtime" | None). **Timestamps only**, never process liveness."""
    if isinstance(info, dict) and info.get("acquired_at") not in (None, ""):
        try:
            return max(0.0, time.time() - float(info["acquired_at"])), "acquired_at"
        except Exception:
            pass
    try:
        return max(0.0, time.time() - float(os.path.getmtime(path))), "mtime"
    except Exception:
        return None, None


def _lock_holder_of(info):
    if not isinstance(info, dict) or info.get("_unparsable"):
        return None
    h = info.get("holder")
    return str(h) if h not in (None, "") else None


def _lock_line(res):
    """Lock result → the unified lock line in the return body/jsonl (auditable timing: how long we waited, who holds it, whether an expired lock was broken)."""
    if not res:
        return {"enabled": False, "holder": None, "waited_ms": 0, "acquired": False,
                "stale_broken": False, "path": None, "reason": "lock=false"}
    return {"enabled": True, "holder": res.get("holder"), "waited_ms": int(res.get("waited_ms") or 0),
            "acquired": bool(res.get("acquired")), "stale_broken": bool(res.get("stale_broken")),
            "path": res.get("path")}


def _lock_acquire(path, holder, ttl_s, wait_s=0.0, note=""):
    """Atomic acquire (O_CREAT|O_EXCL); if taken, **judge TTL by timestamp**: break it when expired (record stale_broken), otherwise poll for wait_s."""
    t0 = time.perf_counter()
    ttl = float(ttl_s) if ttl_s else LOCK_DEFAULT_TTL_S
    wait = max(0.0, float(wait_s or 0.0))
    deadline = t0 + wait
    stale_broken, stale_note = False, None
    parse_err = None
    while True:
        try:
            d = os.path.dirname(path)
            if d:
                os.makedirs(d, exist_ok=True)
            fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            fd = None
        except Exception as e:
            return {"ok": False, "action": "acquire", "acquired": False, "holder": holder, "path": path,
                    "waited_ms": int(round((time.perf_counter() - t0) * 1000.0)),
                    "error": "cannot create the lock file: %s: %s" % (type(e).__name__, str(e)[:160])}
        if fd is not None:
            payload = {"holder": str(holder), "pid": os.getpid(), "acquired_at": time.time(),
                       "ttl_s": ttl, "note": str(note or "")}
            try:
                os.write(fd, _j(payload).encode("utf-8"))
                try:
                    os.fsync(fd)          # Flush to disk: other processes must read complete JSON (not a half-written one)
                except Exception:
                    pass
            finally:
                try:
                    os.close(fd)
                except Exception:
                    pass
            return {"ok": True, "action": "acquire", "acquired": True, "holder": str(holder),
                    "pid": os.getpid(), "acquired_at": payload["acquired_at"], "ttl_s": ttl,
                    "path": path, "waited_ms": int(round((time.perf_counter() - t0) * 1000.0)),
                    "stale_broken": stale_broken, "stale_note": stale_note, "parse_error": parse_err,
                    "note": str(note or ""),
                    "hint": "Be sure to release after rendering: render_lock(action=\"release\", holder=%r%s)"
                            % (str(holder), (", dir=%r" % os.path.dirname(os.path.dirname(path))) if path else "")}
        # ---- Already taken: read it, judge expiry by **timestamp**
        info, err = _lock_read(path)
        age, age_src = _lock_age(info, path)
        if err is not None and err != "missing":
            parse_err = err
        cur_holder = _lock_holder_of(info)
        stale = (err == "missing") or (age is not None and age > ttl)
        if stale:
            try:
                os.remove(path)
                stale_broken = True
                stale_note = ("expired lock broken: holder=%s age=%.1fs(%s) > ttl=%.1fs%s"
                              % (cur_holder or "?", (age if age is not None else -1.0), age_src or "?",
                                 ttl, ("; lock file parse failed: %s" % parse_err) if parse_err else ""))
            except FileNotFoundError:
                stale_broken = True          # another process broke it first: the next O_EXCL round creates it ourselves
                stale_note = "the lock was broken/released by another process after we read it (race; this round retries creation directly)"
            except Exception as e:
                return {"ok": False, "action": "acquire", "acquired": False, "holder": holder, "path": path,
                        "waited_ms": int(round((time.perf_counter() - t0) * 1000.0)),
                        "stale_broken": stale_broken,
                        "error": "the lock has expired but cannot be deleted: %s: %s (permissions/in use?)" % (type(e).__name__, str(e)[:160])}
            continue                         # retry O_EXCL immediately (no sleep)
        if time.perf_counter() >= deadline:
            return {"ok": False, "action": "acquire", "acquired": False, "holder": holder,
                    "current_holder": cur_holder, "path": path, "ttl_s": ttl,
                    "holder_age_s": (round(age, 1) if age is not None else None),
                    "holder_age_source": age_src, "parse_error": parse_err,
                    # how long until the other side expires (null when the age is unavailable, no guessing): if wait_s is smaller, do not wait it out
                    "holder_ttl_remaining_s": (round(max(0.0, ttl - age), 1) if age is not None else None),
                    "waited_ms": int(round((time.perf_counter() - t0) * 1000.0)),
                    "stale_broken": stale_broken, "stale_note": stale_note,
                    "error": "render lock is taken: waited the full wait_s=%.1fs without acquiring it (current holder=%s%s)"
                             % (wait, cur_holder or "?",
                                (", held for %.1fs" % age) if age is not None else ", hold time unreadable"),
                    "hint": "Raise wait_s (or lock_wait_s of qc_render_views); inspect the holder with render_lock(action=\"status\"); "
                            "if you are sure the other process is dead, use render_lock(action=\"release\", holder=<holder>) or wait for the TTL to expire"
                            " (holder_ttl_remaining_s says how long that is)"}
        time.sleep(min(LOCK_POLL_S, max(0.0, deadline - time.perf_counter())))


def _lock_release(path, holder):
    """Release the lock: **delete only when the holder matches** (mismatch → ok:false and report the current holder; never delete someone else's lock)."""
    info, err = _lock_read(path)
    if err == "missing":
        return {"ok": True, "action": "release", "released": False, "holder": str(holder), "path": path,
                "reason": "the lock file does not exist (never acquired / already released / expired and broken)"}
    if err is not None or info.get("_unparsable"):
        return {"ok": False, "action": "release", "released": False, "holder": str(holder), "path": path,
                "current_holder": None, "parse_error": err,
                "error": "cannot parse the lock file, so the holder cannot be confirmed → refusing to delete (to avoid deleting someone else's lock)",
                "hint": "Once the TTL expires the next acquire will break it; or delete %s after checking by hand" % path}
    cur = _lock_holder_of(info)
    if cur != str(holder):
        return {"ok": False, "action": "release", "released": False, "holder": str(holder), "path": path,
                "current_holder": cur,
                "error": "holder mismatch, refusing to release (current holder=%s)" % (cur or "?")}
    try:
        os.remove(path)
    except FileNotFoundError:
        return {"ok": True, "action": "release", "released": False, "holder": str(holder), "path": path,
                "reason": "the lock was already broken/released by another process before this release (idempotent, not a failure)"}
    except Exception as e:
        return {"ok": False, "action": "release", "released": False, "holder": str(holder), "path": path,
                "error": "failed to delete the lock: %s: %s" % (type(e).__name__, str(e)[:160])}
    return {"ok": True, "action": "release", "released": True, "holder": str(holder), "path": path,
            "held_ms": (int(round((time.time() - float(info.get("acquired_at"))) * 1000.0))
                        if info.get("acquired_at") else None)}


def _lock_status(path, ttl_s=None):
    """Inspect the lock: current holder / how long it has been held / remaining TTL / whether it is stale (read-only, changes nothing)."""
    info, err = _lock_read(path)
    if err == "missing":
        return {"ok": True, "action": "status", "path": path, "held": False, "holder": None,
                "hint": "there is no lock right now (you can acquire)"}
    age, age_src = _lock_age(info, path)
    if info.get("_unparsable"):
        ttl = float(ttl_s or LOCK_DEFAULT_TTL_S)
        return {"ok": True, "action": "status", "path": path, "held": True, "holder": None,
                "parse_error": err, "raw": info.get("_raw"), "ttl_s": ttl,
                "age_s": (round(age, 1) if age is not None else None), "age_source": age_src,
                "remaining_s": (max(0.0, ttl - age) if age is not None else None),
                "stale": (age is not None and age > ttl),
                "note": "cannot parse the lock file: holder unknown (no guessing), expiry falls back to the file mtime"}
    ttl = float(ttl_s or info.get("ttl_s") or LOCK_DEFAULT_TTL_S)
    return {"ok": True, "action": "status", "path": path, "held": True,
            "holder": _lock_holder_of(info), "pid": info.get("pid"), "ttl_s": ttl,
            "acquired_at": info.get("acquired_at"), "age_s": (round(age, 1) if age is not None else None),
            "age_source": age_src, "remaining_s": (max(0.0, ttl - age) if age is not None else None),
            "stale": (age is not None and age > ttl), "note": info.get("note") or ""}


def render_lock(args=None):
    """Cross-process render lock primitive (v0.9.1 E1): action="acquire" | "release" | "status".

    blender_rt_plan(op="qc_render_lock", args={"action": "acquire", "holder": "me"})   # or plan(op="render_lock")
    K.dsh_qc_render_api("render_lock", {"action": "status"})

    Arguments:
      action  acquire (default status) | release | status
      holder  holder name (default = DSH_SESSION → DSH_RUN_ID → pid-<pid>)
      ttl_s   lease seconds (default 600): **expiry is judged only from the acquired_at timestamp inside the lock file**
      wait_s  max seconds to wait when it cannot be taken (default 0 = return ok:false immediately; poll interval 0.25s)
      note    note (written into the lock file so others can see what you are running)
      dir     lock base directory (default _work_dir()) → lock file <dir>/locks/render.lock
    """
    a = _unpack_args(args)
    action = str(a.get("action") or a.get("op") or "status").strip().lower()
    holder = str(a.get("holder") or _lock_holder_default())
    note = str(a.get("note") or "")
    base = a.get("dir") or a.get("lock_dir") or a.get("lock_base")
    path = _lock_path(base)
    try:
        ttl_s = float(a.get("ttl_s") if a.get("ttl_s") is not None else LOCK_DEFAULT_TTL_S)
        wait_s = float(a.get("wait_s") or 0.0)
    except Exception as e:
        return _j({"ok": False, "action": action, "error": "ttl_s/wait_s is not a number: %s" % str(e)[:120],
                   "path": path})
    warnings = []
    if ttl_s <= 0:
        warnings.append("ttl_s=%r ≤ 0: treated as the default %.0fs (a TTL≤0 makes the lock expire the moment it is written, i.e. no lock at all)"
                        % (a.get("ttl_s"), LOCK_DEFAULT_TTL_S))
        ttl_s = LOCK_DEFAULT_TTL_S
    if wait_s < 0:
        warnings.append("wait_s=%r < 0: treated as 0" % (a.get("wait_s"),))
        wait_s = 0.0
    if action in ("acquire", "acquire_lock", "get", "lock"):
        res = _lock_acquire(path, holder, ttl_s, wait_s, note)
    elif action in ("release", "unlock", "free"):
        res = _lock_release(path, holder)
    elif action in ("status", "state", "check"):
        res = _lock_status(path, ttl_s)
    else:
        return _j({"ok": False, "action": action, "path": path,
                   "error": "unknown action (only acquire/release/status)",
                   "actions": ["acquire", "release", "status"]})
    out = dict(res)
    out["version"] = QC_RENDER_VERSION
    out["lock_dir"] = os.path.dirname(os.path.dirname(path))
    out["holder_default"] = (str(holder) == _lock_holder_default())
    if warnings:
        out["warnings"] = warnings
    if out.get("stale_broken"):
        out.setdefault("warnings", []).append(out.get("stale_note") or "broke an expired lock")
    return _j(out)
