# -*- coding: utf-8 -*-
"""asm_export stage 5: append-only merge_ledger.jsonl append."""
from ..common import *  # noqa: F401,F403
from .helpers import *  # noqa: F401,F403


def _asm_ledger_events(ctx):
    """Build the merge/export events; returns the events list."""
    mn = ctx["nm"]
    summary = ctx["summary"]
    ts = time.strftime("%Y-%m-%d %H:%M:%S")
    events = []
    merge_slim = ctx["merge_slim"]
    if ctx["flags"]["merge"] and merge_slim is not None:
        events.append({
            "ts": ts, "action": "merge", "name": mn,
            "manifest_md5": merge_slim.get("manifest_md5"),
            "files": [os.path.basename(str(merge_slim.get("outputs", {}).get("blend") or ctx["merge_out_blend"]))]
            if isinstance(merge_slim.get("outputs"), dict) else [os.path.basename(ctx["merge_out_blend"])],
            "md5": {"blend": (merge_slim.get("outputs") or {}).get("md5")
                    if isinstance(merge_slim.get("outputs"), dict) else None},
            "gate_verdict": (merge_slim.get("gate") or {}).get("verdict"),
            "objects": merge_slim.get("objects_total"),
            "tool": "asm_merge", "version": ASSEMBLY_VERSION})
    events.append({
        "ts": ts, "action": "export", "name": mn, "dir": ctx["od"],
        "manifest_md5": ctx["mid"],
        "files": [os.path.basename(str(ctx["files"][k])) for k in ctx["ok_formats"] if ctx["files"].get(k)],
        "md5": {k: ctx["md5map"].get(k) for k in ctx["ok_formats"]},
        "gate_verdict": (ctx["gate_slim"] or {}).get("verdict"),
        "objects": summary["counts"].get("objects"),
        "formats": ctx["ok_formats"], "failed": ctx["failed"],
        "tool": "asm_export", "version": ASSEMBLY_VERSION})
    return events


def _asm_ledger_stage(ctx):
    """Append to the ledger (on failure only append a warning and set files.ledger to None); returns ctx."""
    ctx["ledger_rec"] = None
    if not ctx["flags"]["ledger"]:
        return ctx
    ledger_rec = _asm_ledger_append(ctx["ledger_path"], _asm_ledger_events(ctx))
    if not ledger_rec.get("ok"):
        ctx["warnings"].append("ledger append failed: %s" % str(ledger_rec.get("error"))[:200])
        ctx["files"]["ledger"] = None
    else:
        ctx["md5map"]["ledger"] = _asm_md5_file(ctx["ledger_path"])
    ctx["ledger_rec"] = ledger_rec
    return ctx
