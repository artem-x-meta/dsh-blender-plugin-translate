"""DSH inner-loop runner v2 —— high-frequency iteration on the Blender main thread; the model only sets the goal and the acceptance.

New in v2: multi-objective/constraint penalty terms (penalize), annealing step size (anneal / ns["frac"]), candidate board (top_k / group_key / record),
cross-object batching (treat the object index as a parameter dimension + keep the best of each group via group_key), export a reusable script (dsh_loop_export), contract quick reference (dsh_loop_help).

spec fields:
    setup / step / measure      source-code strings; shared namespace ns (variables written by step are readable in measure)
    iterations / budget_ms      hard limits (required)
    interval                    seconds between ticks (0 = the fastest the event loop allows)
    measure_every / minimize    measurement frequency / minimize or maximize
    patience                    plateau early stop (v0.9.4): finish after this many consecutive measures without refreshing best
                                (0 = off, off by default; stop_reason records "plateau"). It only affects "when to stop",
                                not the behaviour of each iteration — measured timer floor ≈5.7 ms/tick (176 tps),
                                no "dynamic frequency adjustment" (that knob is already measure_every)
    top_k                       candidate board capacity (0 = off); board is deduplicated and sorted by score
    group_key                   grouping dimension name (e.g. "obj") → top_k kept per group (for cross-object batching)
    redraw_every / history_max  redraw frequency (0 = no redraw, fastest) / metric tail length

What measure can write:
    ns["score"]       required (numeric; lower is better / higher is better depending on minimize)
    ns["params"]      parameter dict (returned together with best on convergence)
    ns["metrics"]     named metric dict (e.g. {"ex":..,"ey":..,"ez":..}) → returned with best/board
    ns["violations"]  violation amounts as a list or dict (>0 counts as a violation, used by penalize)
namespace presets: bpy / K / math / random / numpy(np) / i / frac / st / penalize / anneal / record
"""
import bpy, json, math, random, time, traceback

RUNNER_VERSION = 3


import sys as _sys_kit
_KIT = getattr(_sys_kit.modules.get("dsh_rt_kernel"), "dsh_kit", None)
if _KIT is None:
    raise RuntimeError("runner needs the shared kernel K.dsh_kit (injected by KERNEL_BOOTSTRAP)")


_j = _KIT.j  # shared kernel (the original built-in implementation was removed)
def _clean(v):
    """Turn a value from ns into a JSON-able shape (numpy scalars/arrays, Vector, etc.)"""
    try:
        if v is None or isinstance(v, (bool, int, float, str)):
            return v
        if isinstance(v, dict):
            return {str(k): _clean(x) for k, x in v.items()}
        if isinstance(v, (list, tuple)):
            return [_clean(x) for x in v]
        return [float(x) for x in v]
    except Exception:
        try:
            return float(v)
        except Exception:
            return str(v)


def penalize(errors=None, violations=None, weights=None, lam=1.0):
    """Multi-objective + constraint penalty: score = Σ w_i·E_i + λ·Σ max(0, violation)"""
    if errors is None:
        errors = {}
    if isinstance(errors, (list, tuple)):
        errs = [float(x) for x in errors]
        total = 0.0
        for idx, e in enumerate(errs):
            w = 1.0
            if weights is not None:
                if isinstance(weights, (list, tuple)):
                    w = float(weights[idx]) if idx < len(weights) else 1.0
                elif isinstance(weights, dict):
                    w = float(weights.get(str(idx), 1.0))
            total += w * e
    else:
        total = 0.0
        for k, e in errors.items():
            w = 1.0
            if weights is not None:
                if isinstance(weights, dict):
                    w = float(weights.get(k, 1.0))
                elif isinstance(weights, (list, tuple)):
                    w = float(weights[list(errors.keys()).index(k)]) if len(weights) > list(errors.keys()).index(k) else 1.0
            total += w * float(e)
    pen = 0.0
    if violations:
        vals = violations.values() if isinstance(violations, dict) else violations
        for v in vals:
        # violation amount: only > 0 is penalized
            try:
                v = float(v)
            except Exception:
                continue
            if v > 0:
                pen += v
    return float(total + float(lam) * pen)


def anneal(v_start, v_end, frac, power=1.0):
    """Annealing: move from v_start to v_end linearly (or to the power) with progress frac. The step usually has v_start > v_end"""
    f = max(0.0, min(1.0, float(frac)))
    if power and float(power) != 1.0:
        f = f ** float(power)
    return float(v_start) + (float(v_end) - float(v_start)) * f


def _state():
    import sys
    K = sys.modules.get("dsh_rt_kernel")
    if K is None:
        raise RuntimeError("the inner-loop runner needs the persistent kernel K (via the blender_rt_do / engine.act channel)")
    st = getattr(K, "dsh_loop", None)
    if st is None:
        st = {"running": False, "i": 0, "t0": 0.0, "spec": None, "ns": {}, "best": None,
              "history": [], "board": [], "board_groups": {}, "error": None, "stop": False,
              "done": False, "stop_reason": None, "tps": 0.0, "elapsed_ms": 0.0,
              "timer": None, "step_code": None, "measure_code": None, "version": RUNNER_VERSION}
        K.dsh_loop = st
    return st


def _redraw():
    try:
        for a in bpy.context.screen.areas:
            a.tag_redraw()
    except Exception:
        pass


def _finish(st, reason):
    st["running"] = False
    st["done"] = True
    st["stop_reason"] = reason
    dt = time.perf_counter() - st["t0"]
    st["elapsed_ms"] = round(dt * 1000.0, 1)
    st["tps"] = round(st["i"] / dt, 1) if dt > 0 else 0.0
    fn = st.get("timer")
    if fn is not None:
        try:
            bpy.app.timers.unregister(fn)
        except Exception:
            pass
    _redraw()


def _key(entry):
    return _j(entry.get("params"))


def _insert_sorted(lst, entry, minimize, topk):
    k = _key(entry)
    for i, e in enumerate(lst):
        if _key(e) == k:
            better = entry["score"] < e["score"] if minimize else entry["score"] > e["score"]
            if better:
                lst.pop(i)
                break
            return
    lst.append(entry)
    lst.sort(key=lambda e: e["score"], reverse=(not minimize))
    del lst[int(topk):]


def _track(st, spec, entry):
    minimize = spec["minimize"]
    prev = st["best"]
    if prev is None or (entry["score"] < prev["score"] if minimize else entry["score"] > prev["score"]):
        st["best"] = entry
        st["last_improve_i"] = st["i"]      # v0.9.4: the plateau criterion only looks at "the last iteration that refreshed best"
    hist = st["history"]
    hist.append(entry["score"])
    if len(hist) > spec["history_max"]:
        del hist[0]
    topk = int(spec.get("top_k") or 0)
    if topk > 0:
        gk = spec.get("group_key")
        if gk:
            p = entry.get("params") or {}
            g = str(p.get(gk))
            lst = st["board_groups"].setdefault(g, [])
            _insert_sorted(lst, entry, minimize, topk)
        else:
            _insert_sorted(st["board"], entry, minimize, topk)


def _make_recorder(st, spec):
    def record(params=None, score=None, metrics=None, violations=None):
        """Manually record a candidate from measure (uses the current ns values by default)"""
        if score is None:
            raise ValueError("record() needs score")
        e = {"score": float(score), "i": st["i"], "params": _clean(params), "metrics": _clean(metrics),
             "violations": _clean(violations), "t_ms": round((time.perf_counter() - st["t0"]) * 1000.0, 1)}
        topk = int(spec.get("top_k") or 0)
        if topk > 0:
            gk = spec.get("group_key")
            if gk and isinstance(e["params"], dict):
                _insert_sorted(st["board_groups"].setdefault(str(e["params"].get(gk)), []), e, spec["minimize"], topk)
            else:
                _insert_sorted(st["board"], e, spec["minimize"], topk)
        return e
    return record


def _tick():
    st = _state()
    if not st["running"]:
        return None
    spec = st["spec"]
    try:
        now = time.perf_counter()
        if st["stop"]:
            _finish(st, "stopped")
            return None
        if st["i"] >= spec["iterations"]:
            _finish(st, "iterations")
            return None
        if (now - st["t0"]) * 1000.0 >= spec["budget_ms"]:
            _finish(st, "budget")
            return None
        ns = st["ns"]
        ns["i"] = st["i"]
        ns["frac"] = (st["i"] / float(spec["iterations"])) if spec["iterations"] else 0.0
        exec(st["step_code"], ns)
        st["i"] += 1
        if st["i"] % spec["measure_every"] == 0:
            exec(st["measure_code"], ns)
            score = ns.get("score")
            if score is not None:
                entry = {"score": float(score), "i": st["i"], "params": _clean(ns.get("params")),
                         "metrics": _clean(ns.get("metrics")), "violations": _clean(ns.get("violations")),
                         "t_ms": round((now - st["t0"]) * 1000.0, 1)}
                st["last"] = entry["score"]
                _track(st, spec, entry)
                # v0.9.4: plateau early stop — judged only once "a best already exists", so a loop whose measure never supplies score is not killed by mistake
                if (spec["patience"] > 0 and st["best"] is not None
                        and (st["i"] - int(st.get("last_improve_i") or 0)) >= spec["patience"]):
                    _finish(st, "plateau")
                    return None
        if spec["redraw_every"] and st["i"] % spec["redraw_every"] == 0:
            _redraw()
        return spec["interval"]
    except StopIteration:
        _finish(st, "converged")
        return None
    except BaseException:
        st["error"] = traceback.format_exc(limit=4)
        _finish(st, "error")
        return None


def _status_dict(st, history=8, board=0):
    spec = st.get("spec") or {}
    now = time.perf_counter()
    if st["running"]:
        dt = (now - st["t0"]) or 1e-9
        elapsed = dt * 1000.0
        tps = round(st["i"] / dt, 1)
    else:
        elapsed = st.get("elapsed_ms", 0.0)
        tps = st.get("tps", 0.0)
    d = {
        "running": st["running"], "done": st.get("done", False), "i": st["i"],
        "iterations": spec.get("iterations"), "elapsed_ms": round(elapsed, 1), "tps": tps,
        "best": st["best"], "last": st.get("last"), "history_tail": st["history"][-int(history):],
        "error": st["error"], "stop_reason": st.get("stop_reason"),
        "patience": spec.get("patience"), "last_improve_i": st.get("last_improve_i"),
        "board_size": len(st.get("board") or []), "board_groups": len(st.get("board_groups") or {}),
        "runner_version": RUNNER_VERSION,
    }
    if board:
        d["board"] = _board_payload(st, int(board))
    return d


def _board_payload(st, limit):
    out = {"flat": (st.get("board") or [])[:limit]}
    groups = st.get("board_groups") or {}
    if groups:
        out["groups"] = {k: v[:limit] for k, v in list(groups.items())[:limit * 4]}
    return out


def dsh_loop_start(spec=None, **kw):
    st = _state()
    if st["running"]:
        return _j({"ok": False, "err": "loop already running", "status": _status_dict(st)})
    raw = dict(spec or {})
    raw.update(kw)
    s = {
        "setup": raw.get("setup") or "",
        "step": raw.get("step") or "pass",
        "measure": raw.get("measure") or "pass",
        "iterations": int(raw.get("iterations") or 1000),
        "budget_ms": float(raw.get("budget_ms") or 10000),
        "interval": float(raw.get("interval") or 0.0),
        "measure_every": max(1, int(raw.get("measure_every") or 1)),
        # v0.9.4 plateau early stop: stop after patience consecutive measures without refreshing best (0 = off, keeps the old behaviour)
        "patience": max(0, int(raw.get("patience") or 0)),
        "minimize": bool(raw.get("minimize", True)),
        "top_k": int(raw.get("top_k") or 0),
        "group_key": (str(raw.get("group_key")) if raw.get("group_key") else None),
        "redraw_every": int(raw.get("redraw_every", 0)),
        "history_max": int(raw.get("history_max") or 400),
    }
    st.update({"running": True, "i": 0, "t0": time.perf_counter(), "spec": s, "ns": {}, "last_improve_i": 0,
               "best": None, "history": [], "board": [], "board_groups": {}, "error": None,
               "stop": False, "done": False, "stop_reason": None, "last": None, "tps": 0.0})
    try:
        st["step_code"] = compile(s["step"], "<dsh_loop.step>", "exec")
        st["measure_code"] = compile(s["measure"], "<dsh_loop.measure>", "exec")
        ns = st["ns"]
        ns["bpy"] = bpy
        ns["K"] = __import__("sys").modules.get("dsh_rt_kernel")
        ns["math"] = math
        ns["random"] = random
        ns["penalize"] = penalize
        ns["anneal"] = anneal
        ns["record"] = _make_recorder(st, s)
        try:
            import numpy as _np
            ns["np"] = _np
        except Exception:
            pass
        # ★ namespace self-reference (fixed in v1.0.3): the README / cookbook / tool description / recipes all write ns["params"] / ns["score"],
        #   but inside exec(code, ns) the name `ns` **does not** exist automatically — without these two lines, the first line of step
        #   raises NameError: name 'ns' is not defined and the inner loop ends in error within 1 tick (best / board all empty).
        #   Measured (before the fix): start_ok=true → stop_reason="error" / i=0 / board_n=0 (run-muu3oj9hlcjh).
        #   This is the real reason "the inner loop exists but nobody can use it": the documented usage blew up on the first run.
        ns["ns"] = ns
        ns["st"] = st
        if s["setup"]:
            exec(compile(s["setup"], "<dsh_loop.setup>", "exec"), ns)
    except BaseException:
        st["error"] = traceback.format_exc(limit=4)
        st["running"] = False
        return _j({"ok": False, "err": "setup/compile failed", "error": st["error"]})
    st["timer"] = _tick
    bpy.app.timers.register(_tick, first_interval=0.0, persistent=False)
    return _j({"ok": True, "started": True, "runner_version": RUNNER_VERSION,
               "limits": {"iterations": s["iterations"], "budget_ms": s["budget_ms"],
                          "interval": s["interval"], "measure_every": s["measure_every"], "patience": s["patience"],
                          "minimize": s["minimize"], "top_k": s["top_k"], "group_key": s["group_key"]}})


def dsh_loop_status(history=8, board=0):
    return _j(_status_dict(_state(), history, board))


def dsh_loop_stop():
    st = _state()
    st["stop"] = True
    return _j({"ok": True, "stopping": True, "i": st["i"]})


def dsh_loop_board(limit=10, groups=True):
    st = _state()
    payload = _board_payload(st, int(limit))
    if not groups:
        payload.pop("groups", None)
    return _j({"ok": True, "best": st["best"], "board": payload})


def dsh_loop_export(path=None, top=1, include_variants=False, note=""):
    """Export best (or the top-K candidates) as a reusable script: embeds the setup source + the optimal parameters, and applies them directly."""
    st = _state()
    spec = st.get("spec") or {}
    best = st.get("best")
    if best is None:
        return _j({"ok": False, "err": "no result yet (best is empty)"})
    variants = []
    if include_variants:
        if spec.get("group_key"):
            # batch case: take each group's (object's) own best instead of the global top-k
            pool = [lst[0] for _g, lst in sorted((st.get("board_groups") or {}).items()) if lst]
        else:
            pool = list(st.get("board") or [])
        pool.sort(key=lambda e: e["score"], reverse=(not spec.get("minimize", True)))
        seen = set()
        for e in pool:
            k = _json_key(e)
            if k in seen:
                continue
            seen.add(k)
            variants.append(e)
            if len(variants) >= max(1, int(top)):
                break
    payload = {"score": best["score"], "params": best.get("params"), "metrics": best.get("metrics"),
               "i": best["i"], "t_ms": best.get("t_ms"), "note": note,
               "spec": {"iterations": spec.get("iterations"), "budget_ms": spec.get("budget_ms"),
                        "minimize": spec.get("minimize"), "group_key": spec.get("group_key"),
                        "top_k": spec.get("top_k")}}
    setup_src = spec.get("setup") or ""
    lines = [
        "# -*- coding: utf-8 -*-",
        "# Reusable script exported by the DSH inner-loop runner v%d (best score + setup source + apply steps)" % RUNNER_VERSION,
        "# Usage: blender_rt_do(code=<contents of this file>) or exec this script in Blender → reproduce the parameters it found",
        "import json",
        "BEST = json.loads(" + _py_lit(json.dumps(payload, ensure_ascii=False, indent=2)) + ")",
        "SETUP_SRC = json.loads(" + _py_lit(json.dumps(setup_src, ensure_ascii=False)) + ")",
        "VARIANTS = json.loads(" + _py_lit(json.dumps(variants, ensure_ascii=False)) + ") if " + ("True" if include_variants else "False") + " else []",
        "_ns = {}",
        "exec(SETUP_SRC, _ns)",
        "_apply = _ns.get(\"apply\")",
        "if _apply is None:",
        "    raise RuntimeError(\"setup does not define apply(params), so it cannot be reproduced automatically; use BEST[\\\"params\\\"] by hand\")",
        "_seen = set()",
        "_apply(BEST[\"params\"])",
        "_seen.add(json.dumps(BEST[\"params\"], sort_keys=True))",
        "_applied = 1",
        "for _v in VARIANTS:",
        "    _k = json.dumps(_v.get(\"params\"), sort_keys=True)",
        "    if _k in _seen:",
        "        continue",
        "    _seen.add(_k)",
        "    _apply(_v[\"params\"])",
        "    _applied += 1",
        "print(\"APPLIED \" + json.dumps({\"score\": BEST[\"score\"], \"params\": BEST[\"params\"], \"variants_applied\": _applied - 1}, ensure_ascii=False))",
    ]
    src = "\n".join(lines) + "\n"
    wrote = None
    if path:
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(src)
            wrote = path
        except Exception as e:
            return _j({"ok": False, "err": "write failed: %s" % e, "script": src[:200]})
    return _j({"ok": True, "path": wrote, "chars": len(src), "best": payload,
               "variants": len(variants), "script": src})


def _py_lit(s):
    return json.dumps(s)


def _json_key(e):
    return _j(e.get("params"))


def dsh_loop_sync(spec=None, progress_path=None, stop_path=None, heartbeat_ms=500,
                  history=8, board=0, **kw):
    """Headless synchronous inner loop (v1.1.0): does not depend on bpy.app.timers, blocks until it finishes and then returns.

    Why it is needed: bpy.app.timers does not fire under blender -b (the runner selftest always drives the tick by hand),
    so a GUI-only loop is unusable on the headless main path. This reuses dsh_loop_start + _tick,
    **without duplicating the evaluation logic**; every heartbeat_ms it writes _status_dict into progress_path so another session can watch it;
    when stop_path appears it sets st["stop"] and the next tick finishes normally (a single thread cannot interrupt a running step).
    """
    import os
    st0 = _state()
    if st0.get("running"):
        return _j({"ok": False, "err": "loop already running", "status": _status_dict(st0)})
    started = dsh_loop_start(spec, **kw)
    try:
        sd = json.loads(started) if isinstance(started, str) else started
    except Exception:
        sd = {}
    if not isinstance(sd, dict) or not sd.get("ok"):
        return started
    last_hb = 0.0
    while True:
        st = _state()
        if not st.get("running"):
            break
        if stop_path and os.path.exists(str(stop_path)):
            st["stop"] = True
        fn = st.get("timer")
        if fn is None:
            break
        fn()
        now = time.perf_counter()
        if progress_path and (now - last_hb) * 1000.0 >= float(heartbeat_ms or 500):
            last_hb = now
            try:
                with open(str(progress_path), "w", encoding="utf-8") as fh:
                    fh.write(_j(_status_dict(st, int(history))))
            except Exception:
                pass
    out = _status_dict(_state(), int(history))
    if int(board or 0) > 0:
        out["board"] = _board_payload(_state(), int(board))
    out["ok"] = not bool(out.get("error"))
    out["sync"] = True
    return _j(out)


def dsh_loop_help():
    return _j({
        "runner_version": RUNNER_VERSION,
        "start": "dsh_loop_start(spec): spec={setup, step, measure, iterations, budget_ms, interval, measure_every, minimize, top_k, group_key, redraw_every, patience}",
        "ns": "setup/step/measure share ns; presets bpy/K/math/random/np/i/frac/st/penalize/anneal/record",
        "measure": "must assign ns[score]; may write ns[params], ns[metrics], ns[violations]",
        "helpers": ["penalize(errors, violations, weights, lam) -> weighted error + λ·Σmax(0,v)",
                    "anneal(v_start, v_end, frac, power) -> annealing step size (use ns[frac])",
                    "record(params, score, metrics, violations) -> manually record a candidate into the candidate board",
                    "ns[i] / ns[frac] -> current iteration number / progress (readable inside step, for adaptive step size)"],
        "ops": "status(history, board) / stop / board(limit, groups) / export(path, top, include_variants) / bench(iterations) / sync(spec, progress_path, stop_path, heartbeat_ms)",
        "multi_objective": "score = penalize({ex,ey,ez}, violations=[max(0,rot-0.9)], weights={ex:1,ey:1,ez:2}, lam=50)",
        "batch": "put the obj dimension in the parameters + group_key=\"obj\" → keep top_k best per group",
        "safety": "iteration/budget dual hard limits + op=stop emergency stop + automatic stop on error; do not do file I/O inside step",
    })


def dsh_loop_bench(iterations=5000):
    import time as _t
    t0 = _t.perf_counter()
    ns = {}
    for k in range(int(iterations)):
        ns["x"] = k + 1
    dt = _t.perf_counter() - t0
    return _j({"iterations": int(iterations), "ms": round(dt * 1000.0, 2),
               "per_iter_us": round(dt / max(1, int(iterations)) * 1e6, 2)})


# execute_code gets a fresh namespace every time → the API is attached to the persistent kernel K, later calls use K.dsh_loop_api[...]
import sys as _sys
_K = _sys.modules.get("dsh_rt_kernel")
def dsh_loop_selftest():
    """Inner-loop self-test: really starts a minimal loop and **drives the tick by hand** (bpy.app.timers does not fire headless, so it calls st["timer"] directly).

    It asserts that measure can see `ns` and that best has a value — exactly the regression fixed in v1.0.3:
    the old version did not bind `ns` into the namespace, so the documented `ns["params"]` / `ns["score"]` form hit
    NameError on the very first tick (the loop had start_ok=true but ended in error immediately, best/board all empty). The old self-test only read status/help
    and "never really started a loop", so this regression survived 6 versions unnoticed.
    """
    import json

    def _d(x):
        return json.loads(x) if isinstance(x, str) else x

    ev = {}
    try:
        if _state().get("running"):
            return _j({"ok": True, "skipped": "loop already running"})
        started = _d(dsh_loop_start({
            "setup": "pass",
            "step": "ns['params'] = {'a': random.uniform(0.0, 1.0)}",
            "measure": "ns['score'] = float(ns['params']['a'])",
            "iterations": 4, "budget_ms": 2000, "top_k": 3,
        }))
        ev["start_ok"] = started.get("ok") is True
        for _ in range(10):
            st2 = _state()
            if not st2.get("running"):
                break
            fn = st2.get("timer")
            if fn is None:
                break
            fn()
        s3 = _d(dsh_loop_status(4))
        ev["ns_bound"] = "ns" in (_state().get("ns") or {})
        ev["i"] = int(s3.get("i") or 0)
        ev["iters_done"] = int(s3.get("i") or 0) >= 4
        ev["best_present"] = isinstance(s3.get("best"), dict)
        ev["no_error"] = not s3.get("error")
        ev["stop_reason"] = s3.get("stop_reason")
        ok_all = all(ev.get(k) is True for k in ("start_ok", "ns_bound", "iters_done", "best_present", "no_error"))
        return _j({"ok": ok_all, "evidence": ev})
    except Exception as e:
        return _j({"ok": False, "evidence": ev, "error": "%s: %s" % (type(e).__name__, str(e)[:200])})



if _K is not None:
    _K.dsh_loop_api = _KIT.Api({
        "dispatch": _KIT.wrap_dispatch(None, {"selftest": dsh_loop_selftest}),"version": RUNNER_VERSION, "start": dsh_loop_start, "status": dsh_loop_status,
                       "stop": dsh_loop_stop, "board": dsh_loop_board, "export": dsh_loop_export,
                       "help": dsh_loop_help, "bench": dsh_loop_bench,
        "sync": dsh_loop_sync, "selftest": dsh_loop_selftest})

# ---- v0.9.1 (93-B1/B2): make the API callable (swap in a dict-subclass instance that returns parsed objects) ----
# Background: K.dsh_x_api used to be a plain dict → in-process api(args) raised TypeError: 'dict' object is not callable;
# and dispatch returned a JSON string, so the caller had to json.loads it itself.
# Now: api("op", {…}) or api({…}) → dict; api["dispatch"](op, json_str) still returns str (the engine contract is unchanged).
# Note: dict is a static type, you cannot assign __class__ on an existing instance (measured TypeError), so it is swapped for a new instance.
_DshApi = _KIT.Api  # shared kernel (the registration lines at the tail need no change)
import sys as _sys_api
_K_api = _sys_api.modules.get("dsh_rt_kernel")
if _K_api is not None and isinstance(getattr(_K_api, "dsh_runner_api", None), dict) \
        and not isinstance(getattr(_K_api, "dsh_runner_api", None), _DshApi):
    _K_api.dsh_runner_api = _DshApi(_K_api.dsh_runner_api)
