# -*- coding: utf-8 -*-
"""asm_export stage 1: argument validation / formats and name / output directory / manifest validation / merge preconditions."""
from ..common import *  # noqa: F401,F403
from .helpers import *  # noqa: F401,F403
from ..manifest import _load_manifest, _manifest_validate
from ..merge import asm_merge
from ..repair import _repair_flag


def _asm_flags(merge, dry_run, include_receipt, ledger, verify):
    """Validate the 5 boolean arguments uniformly; returns (err, flags)."""
    out = {}
    for key, raw in (("merge", merge), ("dry_run", dry_run), ("include_receipt", include_receipt),
                     ("ledger", ledger), ("verify", verify)):
        fixed, ferr = _repair_flag(raw, key)
        if ferr:
            return _err(ferr), None
        out[key] = fixed
    return None, out


def _asm_name_and_formats(formats, name):
    """Validate formats/name; returns (err, fmts, nm, warnings)."""
    fmts, ferr = _asm_export_formats(formats)
    if ferr:
        return _err(ferr), None, None, None
    nm, nwarn = _asm_export_name(name)
    if nm is None:
        return _err(nwarn), None, None, None
    return None, fmts, nm, ([nwarn] if nwarn else [])


def _asm_target_dir(out_dir, warnings):
    """Resolve the output directory; returns (err, od)."""
    if out_dir is not None and not isinstance(out_dir, (str, os.PathLike)):
        return _err("out_dir must be a path string, got %r" % (out_dir,)), None
    if out_dir:
        return None, _path(str(out_dir))
    K = _kernel()
    base = getattr(K, "out_dir", None) if K is not None else None
    od = _path(os.path.join(base or os.path.expanduser("~"), "asm_export"))
    warnings.append("out_dir not given → defaulting to %s" % od)
    return None, od


def _asm_manifest_stage(manifest, merge):
    """Load and optionally validate the manifest; returns (err, m)."""
    m = None
    if manifest is not None:
        m, merr = _load_manifest(manifest)
        if merr:
            return _err(merr), None
        mval = _manifest_validate(m, check_files=bool(merge), check_md5=bool(merge))
        if not mval["ok"]:
            return _err("manifest validation failed (never export from a bad manifest)", errors=mval["errors"][:10],
                        warnings=mval["warnings"][:10]), None
    if merge and m is None:
        return _err("merge=true requires a manifest (an N-way merge needs the part list)"), None
    return None, m


def _asm_merge_stage(ctx):
    """When merge=true, run asm_merge first (including the dry_run plan); returns (fail_body_or_None, merge_rec)."""
    flags = ctx["flags"]
    od, nm, fmts = ctx["od"], ctx["nm"], ctx["fmts"]
    dry_run = flags["dry_run"]
    merge_out_blend = os.path.join(od, nm + "_merged.blend")
    ctx["merge_out_blend"] = merge_out_blend
    if not flags["merge"]:
        return None, None
    merge_call = dict(manifest=ctx["m"], out_blend=merge_out_blend, dry_run=bool(dry_run))
    raw_merge = asm_merge(**merge_call)
    merge_rec = json.loads(raw_merge) if isinstance(raw_merge, str) else raw_merge
    if not isinstance(merge_rec, dict) or not merge_rec.get("ok"):
        gv = ((merge_rec or {}).get("gate") or {}).get("verdict") if isinstance(merge_rec, dict) else None
        body = {"ok": False, "verdict": gv or "fail", "dry_run": bool(dry_run),
                "stage": "merge", "dir": od, "name": nm, "formats": fmts,
                "files": {}, "counts": {"objects": 0, "files": 0},
                "gate": _asm_gate_slim((merge_rec or {}).get("gate")),
                "merge": _asm_merge_slim(merge_rec),
                "md5": {}, "warnings": ctx["warnings"],
                "error": "merge failed / assembly gate not passed ⇒ nothing exported",
                "verdict_line": "asm_export: merge stage failed (%s) → no files exported"
                                % str((merge_rec or {}).get("error"))[:160],
                "hint": "check merge.gate / merge.error first; fix the manifest/geometry and rerun; a failed merge saves no .blend",
                "honest_limits": list(_ASM_EXPORT_LIMITS)}
        return body, None
    return None, merge_rec
