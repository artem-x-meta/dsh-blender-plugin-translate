# -*- coding: utf-8 -*-
"""asm_export stage 3: the real export (per-format export + verification) and the evaluated-mesh summary."""
from ..common import *  # noqa: F401,F403
from .helpers import *  # noqa: F401,F403


def _asm_export_one_format(fmt, objs, path, verify, warnings):
    """Export a single format and verify it on demand; returns the receipt dict (appends a warning on failure)."""
    try:
        rec = _asm_export_one(fmt, objs, path)
        if verify:
            v = _asm_verify_file(fmt, path)
            rec["verify"] = v
            rec["magic_ok"] = v.get("magic_ok")
            rec["ok"] = bool(v.get("ok"))
            if rec.get("md5") is None:
                rec["md5"] = v.get("md5")
            if not rec["ok"]:
                rec["error"] = v.get("error") or "verify failed"
        else:
            rec["verify"] = {"skipped": True, "reason": "verify=false (only checks existence and non-emptiness)"}
            rec["ok"] = bool(rec.get("exists") and (rec.get("bytes") or 0) > 0)
            if not rec["ok"]:
                rec["error"] = "file missing or empty"
    except Exception as e:
        rec = {"ok": False, "path": path,
               "error": "%s: %s" % (type(e).__name__, str(e)[:240]),
               "verify": {"skipped": True, "reason": "export exception"}}
    if not rec.get("ok"):
        warnings.append("%s export/verify failed: %s" % (fmt, str(rec.get("error"))[:180]))
    return rec


def _asm_export_loop(ctx):
    """Export format by format and collect files/md5map/ok/failed."""
    exports, files, md5map = {}, {}, {}
    ok_formats, failed = [], []
    verify = ctx["flags"]["verify"]
    warnings = ctx["warnings"]
    for fmt in ctx["fmts"]:
        path = ctx["planned"][fmt]
        rec = _asm_export_one_format(fmt, ctx["objs"], path, verify, warnings)
        exports[fmt] = rec
        files[fmt] = path
        if rec.get("ok"):
            ok_formats.append(fmt)
            md5map[fmt] = rec.get("md5")
            if fmt == "obj":
                mtl = os.path.splitext(path)[0] + ".mtl"
                if os.path.isfile(mtl):
                    files["obj_mtl"] = mtl
                    md5map["obj_mtl"] = _asm_md5_file(mtl)
        else:
            failed.append(fmt)
    return exports, files, md5map, ok_formats, failed


def _asm_export_all(ctx):
    """Create the directory + export + summarize the evaluated meshes; returns (err, ctx)."""
    od = ctx["od"]
    try:
        os.makedirs(od, exist_ok=True)
    except Exception as e:
        return _err("cannot create the artifacts directory: %s: %s" % (type(e).__name__, str(e)[:200]), dir=od), None
    exports, files, md5map, ok_formats, failed = _asm_export_loop(ctx)
    mmu = float(_KIT.units())
    md, md_errors = _mesh_map(ctx["objs"])
    summary = _asm_mesh_summary(ctx["names"], md, mmu)
    if summary.get("missing"):
        ctx["warnings"].append("these objects have no evaluated mesh (marked missing in the manifest): %s" % summary["missing"][:10])
    manifest_path = ctx["planned"].get("manifest")
    ledger_path = ctx["planned"].get("ledger")
    if ctx["flags"]["include_receipt"]:
        files["manifest"] = manifest_path
    if ctx["flags"]["ledger"]:
        files["ledger"] = ledger_path
    if ctx["flags"]["merge"]:
        files["blend"] = (((ctx["merge_slim"] or {}).get("outputs") or {}).get("blend")
                          or ctx["merge_out_blend"])
    ctx.update({"exports": exports, "files": files, "md5map": md5map, "ok_formats": ok_formats,
                "failed": failed, "mmu": mmu, "summary": summary, "md_errors": md_errors,
                "manifest_path": manifest_path, "ledger_path": ledger_path})
    return None, ctx
