# -*- coding: utf-8 -*-
"""asm_export stage 6: dry_run plan receipt and final receipt (verdict + body)."""
from ..common import *  # noqa: F401,F403
from .helpers import *  # noqa: F401,F403


def _asm_planned_body(ctx):
    """dry_run: receipt with the plan only (no directory created / no export / no ledger write)."""
    names = ctx["names"]
    warnings = ctx["warnings"] + (["merge dry_run: gate skipped (gate=skipped_dry_run)"]
                                 if ctx["flags"]["merge"] else [])
    return {"ok": True, "verdict": "planned", "dry_run": True, "readonly": True,
            "stage": "planned", "dir": ctx["od"], "name": ctx["nm"], "formats": ctx["fmts"],
            "files": ctx["planned"], "objects": list(names)[:200],
            "counts": {"objects": len(names), "formats": len(ctx["fmts"])},
            "gate": ctx["gate_slim"], "merge": ctx["merge_slim"], "md5": {}, "manifest_md5": None,
            "warnings": warnings, "verify": bool(ctx["flags"]["verify"]),
            "verdict_line": "asm_export (dry_run, read-only): plan %d items → %s; no directory created / no export / no ledger write"
                            % (len(names), "/".join(ctx["fmts"])),
            "hint": "dry_run only returns the plan; pass dry_run=false once confirmed (merge=true runs asm_merge(dry_run=false) first)",
            "honest_limits": list(_ASM_EXPORT_LIMITS)}


def _asm_final_verdict(ctx):
    """Final verdict rule (every format failed ⇒ fail; otherwise carry the gate verdict)."""
    warnings = ctx["warnings"]
    if not ctx["ok_formats"]:
        warnings.append("every format failed ⇒ ok:false (see exports[].error)")
        return "fail"
    verdict = (ctx["gate_slim"] or {}).get("verdict") or "unverified"
    if verdict != "pass":
        warnings.append("gate verdict=%s (≠ pass): files were exported but cannot be delivered directly as shipping parts" % verdict)
    return verdict


def _asm_final_body(ctx):
    """Receipt body after a real export completes."""
    verdict = _asm_final_verdict(ctx)
    ok = bool(ctx["ok_formats"])
    names = ctx["names"]
    led = ctx["ledger_rec"] or {}
    return {"ok": ok, "verdict": verdict, "dry_run": False, "stage": "exported",
            "dir": ctx["od"], "name": ctx["nm"], "formats": ctx["fmts"],
            "formats_ok": ctx["ok_formats"], "formats_failed": ctx["failed"],
            "files": ctx["files"], "counts": dict(ctx["summary"]["counts"], files=len(ctx["ok_formats"])),
            "objects": list(names)[:200], "gate": ctx["gate_slim"], "merge": ctx["merge_slim"],
            "md5": ctx["md5map"], "manifest_md5": ctx["mid"],
            "exports": {k: _asm_export_slim(v) for k, v in ctx["exports"].items()},
            "warnings": ctx["warnings"], "verify": bool(ctx["flags"]["verify"]), "ledger": ctx["ledger_rec"],
            "verdict_line": ("asm_export: %d items → %s (ok %s / failed %s) · gate=%s · manifest=%s · ledger=%s"
                             % (len(names), "/".join(ctx["fmts"]), "/".join(ctx["ok_formats"]) or "none",
                                "/".join(ctx["failed"]) or "none", verdict,
                                "written" if ctx["mid"] else "skipped",
                                "appended" if led.get("ok") else "skipped")),
            "hint": ("export complete: read verdict first (degraded≠pass) and warnings; the manifest has per-file md5/bbox")
                    if ok else "every format failed: see exports[].error (GLB needs io_scene_gltf2 / FBX needs io_scene_fbx)",
            "honest_limits": list(_ASM_EXPORT_LIMITS), "md_errors": ctx["md_errors"]}
