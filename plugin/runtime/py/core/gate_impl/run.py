# -*- coding: utf-8 -*-
"""Split from gate.py; behavior preserved by the facade."""
from .common import *  # noqa: F401,F403
from .plan import _aggregate, _collect_echo, _eval_pass_if, _expr_names, _load_spec, _norm_spec, _status_of

def _missing_skip_groups(args, groups):
    """skip_if_missing criterion: each inner group is an OR of candidate key names; if a group gets none of them ⇒ that group is unconfigured."""
    miss = []
    for grp in groups or []:
        keys = [str(k) for k in (grp if isinstance(grp, (list, tuple)) else [grp])]
        if not any(k in (args or {}) for k in keys):
            miss.append(keys)
    return miss


def _norm_overrides(overrides):
    """overrides={gate id: {args key: value}} (v0.9.6): supply the args a preset only "learns on site".
    Example: gate_run(preset="assembly", overrides={"no_clash":{"objects_a":[…],"objects_b":[…]}})."""
    if not overrides:
        return {}
    if isinstance(overrides, str):
        overrides = json.loads(overrides) if overrides.strip() else {}
    if not isinstance(overrides, dict):
        raise ValueError("overrides must be {gate id: {args key: value}}")
    out = {}
    for k, v in overrides.items():
        if not isinstance(v, dict):
            raise ValueError("overrides[%s] must be an object (args key-value)" % k)
        out[str(k)] = v
    return out


def _gate_prepare(spec, spec_path, preset, overrides):
    """Load spec + normalize + merge overrides; returns (sp, src, md5, ov)."""
    data, src, md5 = _load_spec(spec, spec_path, preset)
    sp = _norm_spec(data)
    _ov = _norm_overrides(overrides)
    for g in sp["gates"]:
        if g["id"] in _ov:
            g["args"] = dict(g["args"] or {}, **_ov[g["id"]])
    return sp, src, md5, _ov


def _gate_missing_row(g, api):
    """The gate's module was not preloaded / its source is unconfigured ⇒ emit an error/skipped row straight away (cannot run); return None when it can run."""
    rec = {"id": g["id"], "op": g["op"]}
    attr, _sub = OP_MAP[g["op"]]
    if api is None:
        rec.update({"state": "error", "error": "This gate needs module %s (not injected by preload)" % attr})
        return rec
    # v0.9.6: unconfigured source ⇒ this gate is skipped (not run). Always list it explicitly, and it pushes the top level down to degraded.
    _miss = _missing_skip_groups(g["args"], g.get("skip_if_missing"))
    if _miss:
        rec.update({"state": "skipped", "ms": 0,
                    "reason": "This gate has no configured source (missing %s) ⇒ not checked (skipped ≠ pass; since v3 the top level is degraded because of it)"
                              % " / ".join("|".join(m) for m in _miss),
                    "hint": "To really judge this gate: add these args to the spec, or override them with overrides={'%s':{…}} — "
                            "the top level is pass only when every gate really ran and passed" % g["id"],
                    "skipped_args": _miss})
        return rec
    return None


def _gate_call(api, sub, args):
    """Call the sub-op; returns (sub_receipt, ms, err)."""
    t1 = time.time()
    try:
        return api(sub, args or {}), int((time.time() - t1) * 1000), None
    except Exception as e:
        return None, int((time.time() - t1) * 1000), "%s: %s" % (type(e).__name__, str(e)[:180])


def _gate_envelope_error(rec, sub_receipt):
    """The sub-op reported its own error (bad args / unmet precondition) ⇒ surface its message, do not mislead with a pass_if error."""
    _is_err_env = (isinstance(sub_receipt, dict) and sub_receipt.get("ok") is False
                   and bool(sub_receipt.get("error") or sub_receipt.get("stage") or sub_receipt.get("reason")))
    if not _is_err_env:
        return False
    rec["state"] = "error"
    rec["error"] = str(sub_receipt.get("error") or sub_receipt.get("reason") or "The gate's prerequisite op returned ok=false")[:200]
    rec["key"] = {k: sub_receipt.get(k) for k in ("error", "hint", "reason") if k in sub_receipt}
    return True


def _gate_apply_judgement(g, rec, sub_receipt):
    """pass_if / degrade_if evaluation + key evidence; returning False means criterion evaluation failed (this gate is error)."""
    if g["pass_if"]:
        try:
            got = _eval_pass_if(g["pass_if"], sub_receipt if isinstance(sub_receipt, dict) else {},
                                label="pass_if")
        except Exception as e:
            rec.update({"state": "error", "error": "pass_if evaluation failed: %s" % str(e)[:200]})
            return False
        # v0.9.6 (calibration): **an explicit pass_if rules** — the sub-op's ok=false may just mean "one item failed"
        # (e.g. print_report's overhang) and must not override an explicit criterion; only degraded is the exception:
        # when the underlying run did not finish (ok=null) it must not be read as pass.
        if rec["state"] != "degraded":
            rec["state"] = "pass" if got else "fail"
        rec["pass_if"] = g["pass_if"]
        rec["pass_if_value"] = bool(got)
    # v3: **a true criterion ≠ a trustworthy conclusion**. A degrade_if hit (e.g. min_mm below the measurement
    # resolution) ⇒ this gate is degraded, never a fake pass; fail/degraded are stronger conclusions and are not
    # overridden by degrade_if (fail wins).
    if g.get("degrade_if") and rec["state"] == "pass":
        try:
            _dg = _eval_pass_if(g["degrade_if"], sub_receipt if isinstance(sub_receipt, dict) else {},
                                label="degrade_if")
        except Exception as e:
            rec.update({"state": "error", "error": "degrade_if evaluation failed: %s" % str(e)[:200]})
            return False
        if _dg:
            rec["state"] = "degraded"
            rec["degrade_if"] = g["degrade_if"]
            rec["degrade_reason"] = (g.get("degrade_reason")
                                     or "degrade_if hit: the criterion is true but the evidence is not trustworthy (resolution/coverage insufficient) ⇒ must not count as pass")
            rec["hint"] = "To get a pass: make the measurement basis solid first (finer mesh / adjust min_mm), and see the real readings in echo"
    rec["key"] = {k: sub_receipt.get(k) for k in _expr_names(g["pass_if"]) if isinstance(sub_receipt, dict) and k in sub_receipt}
    if rec["state"] != "pass":
        # only fail/degraded carry more evidence (enough to locate the problem, without stuffing in the whole receipt)
        for k in ("reason", "error", "hint", "state", "clean", "verdict", "count"):
            if isinstance(sub_receipt, dict) and k in sub_receipt and k not in rec["key"]:
                rec["key"][k] = sub_receipt[k]
    return True


def _gate_row(g, detail):
    """One gate: skip / missing module / exception / execution / criterion. Returns (row, stop_kind).

    stop_kind: never (do not break on stop_on_fail) / always (break as soon as execution throws) / if_fail (break only on fail/error).
    """
    attr, sub = OP_MAP[g["op"]]
    api = getattr(_kernel(), attr, None)   # cross-module call: the APIs all hang off dsh_rt_kernel
    miss_row = _gate_missing_row(g, api)
    if miss_row is not None:
        return miss_row, "never"
    rec = {"id": g["id"], "op": g["op"]}
    sub_receipt, ms, call_err = _gate_call(api, sub, g["args"])
    if call_err is not None:
        rec.update({"state": "error", "error": call_err, "ms": ms})
        return rec, "always"
    rec["ms"] = ms
    rec["state"] = _status_of(sub_receipt)
    # v3: echo — carry the declared **real fields** (resolution / min_mm / warning…) into the receipt as evidence (auditable)
    if g.get("echo") and isinstance(sub_receipt, dict):
        rec["echo"] = _collect_echo(sub_receipt, g["echo"])
    if _gate_envelope_error(rec, sub_receipt):
        return rec, "always"
    if not _gate_apply_judgement(g, rec, sub_receipt):
        return rec, "never"
    if detail:
        rec["receipt"] = sub_receipt
    return rec, "if_fail"


def _gate_payload(sp, rows, src, md5, ov, t0):
    """Three-state aggregate receipt (verdict/coverage/skipped_note/overrides)."""
    states = [r.get("state") for r in rows]
    verdict = _aggregate(states)
    _checked = [r["id"] for r in rows if r.get("state") in ("pass", "fail", "degraded", "error")]
    _skipped = [r["id"] for r in rows if r.get("state") == "skipped"]
    payload = {"ok": verdict == "pass", "verdict": verdict, "name": sp["name"], "units": sp["units"],
               "tolerance_mm": sp["tolerance_mm"], "spec_source": src, "spec_md5": md5,
               "gates": rows, "ran": len(rows), "total": len(sp["gates"]),
               "failed": [r["id"] for r in rows if r.get("state") in ("fail", "error")],
               "degraded": [r["id"] for r in rows if r.get("state") == "degraded"],
               # v0.9.6+ v3: skipped gates must be visible, and they **push the top level down to degraded**
               # (skipped ≠ pass; the top level is pass only when every gate really ran and passed)
               "skipped": _skipped,
               "coverage": {"gates": len(sp["gates"]), "checked": len(_checked), "skipped": len(_skipped),
                            "all_gates_ran": not _skipped, "checked_ids": _checked, "skipped_ids": _skipped},
               "ms": int((time.time() - t0) * 1000),
               "note": "The top level always reads verdict (three-state); ok is true only on pass — any gate degraded **or skipped** ⇒ "
                       "top level degraded (fail wins): skipped ≠ pass, and gates nobody checked must not read as green; "
                       "a degrade_if hit is likewise judged degraded (evidence not trustworthy, see echo)"}
    if _skipped:
        payload["skipped_note"] = ("skipped ≠ pass: these gates did not run (no configured source / not applicable): %s — "
                                   "since v3 skipped makes the top level degraded (not pass); "
                                   "to have them take part in the verdict add args or go through overrides" % _skipped)
    if ov:
        payload["overrides_applied"] = {k: sorted(v.keys()) for k, v in ov.items()}
    return payload


def _gate_write_json(payload, out_json):
    """Write out_json to disk (a failure is not fatal; out_json_error is recorded)."""
    try:
        _k = _kernel()
        p = _k.win_path(str(out_json)) if (str(out_json).startswith("/") and _k is not None) else str(out_json)
        d = os.path.dirname(p)
        if d and not os.path.isdir(d):
            os.makedirs(d, exist_ok=True)
        with open(p, "w", encoding="utf-8") as f:
            f.write(_j(payload))
        payload["out_json"] = p
    except Exception as e:
        payload["out_json_error"] = str(e)[:160]
    return payload


def gate_run(spec=None, spec_path=None, preset=None, detail=False, out_json=None, stop_on_fail=False,
             overrides=None):
    """Run the whole package: gate by gate → three-state aggregate. The receipt carries only **the fields the criterion used** by default (self-slimming).

    overrides (v0.9.6): {gate id: {args key: value}} — merged only into that gate's args, criteria unchanged. Parameters of a preset
    that "only the scene knows" (e.g. both sides of a cross-part interference) are filled in through it; gates declaring skip_if_missing
    that were not filled in are recorded as skipped, and **skipped pushes the top level down to degraded** (v3: skipped ≠ pass, it must not
    turn green for a "healthy default preset").

    degrade_if: the criterion is true but the evidence is not trustworthy (e.g. min_mm below the measurement resolution) ⇒ that gate is degraded,
    echo supplies the real readings.
    """
    sp, src, md5, _ov = _gate_prepare(spec, spec_path, preset, overrides)
    t0 = time.time()
    rows = []
    for g in sp["gates"]:
        row, stop_kind = _gate_row(g, detail)
        rows.append(row)
        if stop_on_fail and (stop_kind == "always" or
                             (stop_kind == "if_fail" and row.get("state") in ("fail", "error"))):
            break
    payload = _gate_payload(sp, rows, src, md5, _ov, t0)
    if out_json:
        payload = _gate_write_json(payload, out_json)
    return _j(payload)

