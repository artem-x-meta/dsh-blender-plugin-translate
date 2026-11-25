# -*- coding: utf-8 -*-
"""Split from gate.py; behavior preserved by the facade."""
from .common import *  # noqa: F401,F403

def _load_spec(spec=None, spec_path=None, preset=None):
    """Returns (spec_dict, source, md5). All three are supported: a .py module, a .json, an inline dict."""
    if preset:
        key = str(preset)
        if key not in PRESETS:
            raise ValueError("unknown preset: %s (allowed %s)" % (preset, sorted(PRESETS)))
        raw = _j(PRESETS[key])
        return json.loads(raw), "preset:" + key, _md5_text(raw)
    if spec_path:
        p = str(spec_path)
        _k = _kernel()
        if p.startswith("/"):
            wsl = _k.win_path(p) if _k is not None else p
        else:
            wsl = p
        if not os.path.exists(wsl):
            wsl = p
        with open(wsl, "r", encoding="utf-8") as f:
            text = f.read()
        if wsl.lower().endswith(".py"):
            ns = {}
            exec(compile(text, wsl, "exec"), ns)
            if "SPEC" in ns:
                data = ns["SPEC"]
            else:
                data = {"name": ns.get("NAME", os.path.basename(wsl)), "units": ns.get("UNITS", "mm"),
                        "tolerance_mm": ns.get("TOLERANCE_MM"), "gates": ns.get("GATES")}
        else:
            data = json.loads(text)
        return data, "file:" + wsl, _md5_text(text)
    if isinstance(spec, dict):
        raw = _j(spec)
        return json.loads(raw), "inline", _md5_text(raw)
    raise ValueError("give spec=<dict> or spec_path=<.json/.py> or preset=<name>")


def _norm_spec(data):
    if not isinstance(data, dict):
        raise ValueError("spec must be an object (or SPEC inside a .py)")
    gates = data.get("gates")
    if not isinstance(gates, list) or not gates:
        raise ValueError("spec.gates must be a non-empty array")
    out = {"name": str(data.get("name") or "unnamed"), "units": str(data.get("units") or "mm"),
           "tolerance_mm": data.get("tolerance_mm"), "gates": []}
    for i, g in enumerate(gates):
        if not isinstance(g, dict):
            raise ValueError("gates[%d] must be an object" % i)
        op = str(g.get("op") or "")
        if op not in OP_MAP:
            near = sorted(OP_MAP)
            raise ValueError("gates[%d].op is not recognized: %s (allowed: %s)" % (i, op, ", ".join(near)))
        out["gates"].append({"id": str(g.get("id") or ("g%d" % i)), "op": op,
                             "args": g.get("args") or {}, "pass_if": str(g.get("pass_if") or ""),
                             "note": g.get("note"),
                             # v0.9.6: "none of these keys was given" ⇒ that gate is skipped (not configured/not applicable),
                             # listed explicitly in the receipt's skipped[]; since v3 skipped pushes the top level to degraded. A "group" = an OR over candidate key names.
                             "skip_if_missing": _norm_skip_groups(g.get("skip_if_missing")),
                             # v3: the criterion holds but the evidence is untrustworthy ⇒ degrade; echo brings the real fields into the receipt as evidence.
                             "degrade_if": str(g.get("degrade_if") or ""),
                             "echo": _norm_str_list(g.get("echo"))})
    return out


def _norm_str_list(raw):
    """Normalize echo into [dot paths…] (a single string is accepted too)."""
    if not raw:
        return []
    if isinstance(raw, str):
        return [raw] if raw.strip() else []
    if isinstance(raw, (list, tuple)):
        return [str(x) for x in raw if str(x).strip()]
    raise ValueError("echo must be a dot-path string or an array of them")


def _path_get(root, path):
    """Read a real field by dot path (for echo): `detail.walls.objects.0.resolution_mm`.

    Read-only; any missing/out-of-range segment ⇒ (None, False) (no exception — evidence gathering must not take the gate down).
    """
    cur = root
    for seg in str(path or "").split("."):
        if not seg:
            continue
        if isinstance(cur, dict):
            if seg not in cur:
                return None, False
            cur = cur[seg]
        elif isinstance(cur, (list, tuple)):
            if not seg.lstrip("-").isdigit():
                return None, False
            i = int(seg)
            if not (-len(cur) <= i < len(cur)):
                return None, False
            cur = cur[i]
        else:
            return None, False
    return cur, True


def _collect_echo(receipt, paths):
    """echo: pull the **real fields** at the declared dot paths into the receipt (for evidence). Oversized values are reported as a summary only, so the receipt does not blow up."""
    out = {}
    for p in paths or []:
        v, found = _path_get(receipt, p)
        if not found:
            out[str(p)] = "<field missing>"
            continue
        try:
            s = _j(v)
        except Exception:
            s = None
        out[str(p)] = v if (s is not None and len(s) <= 300) else "<field too large, see detail>"
    return out


def _norm_skip_groups(raw):
    """Normalize skip_if_missing into [[candidate keys…], …] (a flat list is accepted too: ["a","b"] → [["a","b"]])."""
    if not raw:
        return []
    if isinstance(raw, (str, dict)):
        raw = [raw]
    if not isinstance(raw, (list, tuple)):
        raise ValueError("skip_if_missing must be an array (each group is a candidate key name or an array of them)")
    out = []
    if raw and all(isinstance(x, str) for x in raw):
        raw = [list(raw)]
    for grp in raw:
        keys = [str(k) for k in (grp if isinstance(grp, (list, tuple)) else [grp])]
        if keys:
            out.append(keys)
    return out


def _expr_names(expr):
    """Collect the variable names used in the expression (used to slim the reply down to the criterion fields)."""
    names = []
    try:
        tree = ast.parse(expr, mode="eval")
    except SyntaxError:
        return names
    for n in ast.walk(tree):
        if isinstance(n, ast.Name) and n.id not in ALLOWED_FUNCS and n.id not in ("True", "False", "None"):
            if n.id not in names:
                names.append(n.id)
    return names


def _check_ast(node, label="pass_if"):
    ok_types = (ast.Expression, ast.BoolOp, ast.UnaryOp, ast.Compare, ast.Name, ast.Load, ast.Constant,
                ast.Attribute, ast.Subscript, ast.Tuple, ast.List, ast.BinOp, ast.Call,
                ast.And, ast.Or, ast.Not, ast.Eq, ast.NotEq, ast.Lt, ast.LtE, ast.Gt, ast.GtE,
                ast.In, ast.NotIn, ast.Add, ast.Sub, ast.Mult, ast.Div, ast.Mod, ast.USub, ast.UAdd)
    for n in ast.walk(node):
        if not isinstance(n, ok_types):
            raise ValueError("%s contains disallowed syntax: %s" % (label, type(n).__name__))
        if isinstance(n, ast.Call):
            if not isinstance(n.func, ast.Name) or n.func.id not in ALLOWED_FUNCS:
                raise ValueError("%s only allows these functions: %s" % (label, sorted(ALLOWED_FUNCS)))
        if isinstance(n, ast.Attribute) and n.attr.startswith("_"):
            raise ValueError("%s must not access underscore attributes" % label)


# ── v1.0.2 (gate compliance) · restricted AST evaluator ────────────────────────────────────────
# Background: this function used to go through the built-in **dynamic evaluation entry point**. Semantically it was already pinned by `_check_ast` to a tiny
#   subset of syntax (no underscore attributes, calls only to ALLOWED_FUNCS), but that entry point's "name + left paren" alone
#   gets flagged as high by supply-chain scanners (DANGEROUS_DYNAMIC_EXECUTION) — rather than hiding the keyword to pass the check,
#   it is better to write the evaluator as "per-node, whitelist-computed", with the whitelist aligned item by item with `_check_ast` (which is still the only entry).
#   Note: this file and a few other places under runtime/ still "load source with exec and run it" (loading a spec module /
#   running a test script); those are normal usage inside the same restricted kernel, are **not** on that scanner rule, and are therefore left untouched.
_BIN_OPS = {
    ast.Add: lambda a, b: a + b,
    ast.Sub: lambda a, b: a - b,
    ast.Mult: lambda a, b: a * b,
    ast.Div: lambda a, b: a / b,
    ast.Mod: lambda a, b: a % b,
}
_CMP_OPS = {
    ast.Eq: lambda a, b: a == b,
    ast.NotEq: lambda a, b: a != b,
    ast.Lt: lambda a, b: a < b,
    ast.LtE: lambda a, b: a <= b,
    ast.Gt: lambda a, b: a > b,
    ast.GtE: lambda a, b: a >= b,
    ast.In: lambda a, b: a in b,
    ast.NotIn: lambda a, b: a not in b,
}


def _eval_node(node, env, label):
    """Evaluate **node by node** against the whitelist (aligned with the semantics of the old restricted dynamic evaluation).

    Semantics (all differ from the built-in only in the "stricter" direction):
      · names come only from env; a miss → an immediate error (the old version only hit NameError at the empty builtins table);
      · calls only allow ALLOWED_FUNCS, and `*args` / `**kwargs` are unsupported (`_check_ast` never allowed them anyway);
      · BoolOp returns the operand at the short-circuit itself (not a bool), Compare supports chained `a < b < c`; both match Python.
    """
    if isinstance(node, ast.Expression):
        return _eval_node(node.body, env, label)
    if isinstance(node, ast.Constant):
        return node.value
    if isinstance(node, ast.Name):
        if node.id in env:
            return env[node.id]
        raise ValueError("%s uses an unavailable name: %s" % (label, node.id))
    if isinstance(node, ast.UnaryOp):
        val = _eval_node(node.operand, env, label)
        if isinstance(node.op, ast.Not):
            return not val
        if isinstance(node.op, ast.USub):
            return -val
        if isinstance(node.op, ast.UAdd):
            return +val
        raise ValueError("%s has an unsupported unary operator: %s" % (label, type(node.op).__name__))
    if isinstance(node, ast.BoolOp):
        want_and = isinstance(node.op, ast.And)
        val = _eval_node(node.values[0], env, label)
        for nxt in node.values[1:]:
            if (want_and and not val) or ((not want_and) and val):
                return val
            val = _eval_node(nxt, env, label)
        return val
    if isinstance(node, ast.BinOp):
        fn = _BIN_OPS.get(type(node.op))
        if fn is None:
            raise ValueError("%s has an unsupported binary operator: %s" % (label, type(node.op).__name__))
        return fn(_eval_node(node.left, env, label), _eval_node(node.right, env, label))
    if isinstance(node, ast.Compare):
        left = _eval_node(node.left, env, label)
        for op_node, comp in zip(node.ops, node.comparators):
            fn = _CMP_OPS.get(type(op_node))
            if fn is None:
                raise ValueError("%s has an unsupported comparison operator: %s" % (label, type(op_node).__name__))
            right = _eval_node(comp, env, label)
            if not fn(left, right):
                return False
            left = right                      # chained comparison: a < b < c
        return True
    if isinstance(node, ast.Attribute):
        if node.attr.startswith("_"):
            raise ValueError("%s must not access underscore attributes" % label)
        return getattr(_eval_node(node.value, env, label), node.attr)
    if isinstance(node, ast.Subscript):
        sl = node.slice
        if type(sl).__name__ == "Index":      # the ast.Index wrapper of Python < 3.9
            sl = sl.value
        return _eval_node(node.value, env, label)[_eval_node(sl, env, label)]
    if isinstance(node, ast.Tuple):
        return tuple(_eval_node(e, env, label) for e in node.elts)
    if isinstance(node, ast.List):
        return [_eval_node(e, env, label) for e in node.elts]
    if isinstance(node, ast.Call):
        if node.keywords or any(isinstance(a, ast.Starred) for a in node.args):
            raise ValueError("%s does not support *args / **kwargs in function calls" % label)
        if not isinstance(node.func, ast.Name) or node.func.id not in ALLOWED_FUNCS:
            raise ValueError("%s only allows these functions: %s" % (label, sorted(ALLOWED_FUNCS)))
        return env[node.func.id](*[_eval_node(a, env, label) for a in node.args])
    raise ValueError("%s contains disallowed syntax: %s" % (label, type(node).__name__))


def _eval_pass_if(expr, receipt, label="pass_if"):
    """Restricted expression evaluation (shared by `pass_if` and `degrade_if`). Variables come from the receipt's top level; a miss → report exactly which field is missing."""
    tree = ast.parse(expr, mode="eval")
    _check_ast(tree, label)
    env = {"True": True, "False": False, "None": None}
    env.update(ALLOWED_FUNCS)
    missing = []
    for nm in _expr_names(expr):
        if nm in receipt:
            env[nm] = receipt[nm]
        elif nm in ("units", "tolerance_mm"):
            env[nm] = None
        else:
            missing.append(nm)
    if missing:
        raise ValueError("%s references a field the receipt does not have: %s (receipt top-level fields: %s)"
                         % (label, missing, sorted(k for k in receipt if not str(k).startswith("_"))[:14]))
    # v1.0.2: no longer uses the built-in eval — per-node whitelist evaluation (the syntax whitelist is still _check_ast above)
    return bool(_eval_node(tree.body, env, label))


def _aggregate(states):
    """Whole-package three-state (tightened in v3): any fail/error ⇒ fail; otherwise any **degraded or skipped** ⇒ degraded; otherwise pass.

    Minimal fix (Lead decision): **any skipped or degraded gate makes the top level degraded, fail wins** —
    the old rule `pass + skipped = pass` was rejected ("never measured interference" must not go green, and the bar must not be lowered for a "healthy default preset").
    pass is given only when at least one gate really passes and there is no fail/error/degraded/skipped;
    with no gates at all (an empty package) it is also always degraded — "nothing was checked" gives no pass verdict.
    """
    if any(s in ("fail", "error") for s in states):
        return "fail"
    if any(s in ("degraded", "skipped") for s in states):
        return "degraded"
    if not any(s == "pass" for s in states):
        return "degraded"
    return "pass"


_DOMAIN_DEGRADED_VERDICTS = ("unresolved",)     # the "insufficient evidence" name of the domain three-state: equals degraded, must not be read as a pass


def _tri_of(d):
    """Read the three-state from one dict (pass/fail/degraded); None when it cannot be read (the caller keeps looking deeper)."""
    if not isinstance(d, dict):
        return None
    if d.get("ok") is False or d.get("state") == "fail" or d.get("verdict") == "fail":
        return "fail"
    if d.get("ok") is None or d.get("state") == "degraded" or d.get("verdict") == "degraded":
        return "degraded"
    for v in (d.get("state"), d.get("verdict")):
        if v == "pass":
            return "pass"
    return None


def _status_of(receipt):
    """Judge a gate receipt into the three-state: pass / fail / degraded (a receipt that is not an object ⇒ error).

    v0.9.6 (review fix): **the three-state is not always at the top level**. `audit_connectivity`'s top-level `ok` only means "the analysis ran";
    the gate verdict lives in the **nested `gate`** (`gate.state` / `gate.verdict`) — when the top level yields no three-state the nested one must be read,
    otherwise: ① pass_if writing `state` is "referencing a field that does not exist" (always error); ② "not analyzed/unconfirmed ⇒ degraded"
    would be read as pass because the top-level `ok=true` (a false pass). The domain name `unresolved` (insufficient interference evidence) equals degraded.
    """
    if not isinstance(receipt, dict):
        return "error"
    st = _tri_of(receipt)
    if st:
        return st
    if receipt.get("verdict") in _DOMAIN_DEGRADED_VERDICTS:
        return "degraded"
    for key in ("gate", "connectivity"):
        sub = receipt.get(key)
        st = _tri_of(sub)
        if st:
            return st
        if isinstance(sub, dict) and sub.get("verdict") in _DOMAIN_DEGRADED_VERDICTS:
            return "degraded"
    return "pass"


# ---------------------------------------------------------------- ops

def gate_plan(spec=None, spec_path=None, preset=None):
    """Read-only: parse the spec and list the gates and criteria that will run (nothing is executed)."""
    data, src, md5 = _load_spec(spec, spec_path, preset)
    sp = _norm_spec(data)
    rows = []
    for g in sp["gates"]:
        rows.append({"id": g["id"], "op": g["op"], "args": g["args"], "pass_if": g["pass_if"],
                     "reads": _expr_names(g["pass_if"]), "note": g["note"],
                     "skip_if_missing": g["skip_if_missing"] or None,
                     "degrade_if": g["degrade_if"] or None, "echo": g["echo"] or None,
                     "module": OP_MAP[g["op"]][0].replace("dsh_", "").replace("_api", "")})
    return _j({"ok": True, "name": sp["name"], "units": sp["units"], "tolerance_mm": sp["tolerance_mm"],
               "spec_source": src, "spec_md5": md5, "gate_count": len(rows), "gates": rows,
               "presets": sorted(PRESETS),
               "note": "only gate_run really runs; verdict is three-state (pass/fail/degraded) and ok is true only on pass; "
                       "a gate declaring skip_if_missing is recorded as skipped when \"none of these keys was given\" (not run; since v3 skipped pushes the "
                       "top level to degraded — skipped ≠ pass); a degrade_if hit ⇒ that gate is degraded (untrustworthy evidence)"})


