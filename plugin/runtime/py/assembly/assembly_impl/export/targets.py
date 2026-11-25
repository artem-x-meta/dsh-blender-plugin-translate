# -*- coding: utf-8 -*-
"""asm_export stage 2: object resolution and the pre-export gate."""
from ..common import *  # noqa: F401,F403
from .helpers import *  # noqa: F401,F403
from ..gate import asm_gate


def _asm_merge_targets(ctx):
    """Object-name resolution on the merge path; returns (err, names)."""
    merge_rec = ctx["merge_rec"]
    names = []
    if ctx["flags"]["dry_run"]:
        for p in merge_rec.get("parts") or []:
            tn = p.get("target_names") if isinstance(p, dict) else None
            if isinstance(tn, dict):
                names.extend(str(v) for v in tn.values())
        if not names:
            names = [str(x.get("object")) for x in (merge_rec.get("merged") or [])
                     if isinstance(x, dict) and x.get("object")]
        if not names:
            return _err("the merge plan has no exportable object (empty merge)", merge=_asm_merge_slim(merge_rec)), None
        return None, names
    names = [str(x.get("object")) for x in (merge_rec.get("merged") or [])
             if isinstance(x, dict) and x.get("object")]
    if not names:
        return _err("the merge finished but the receipt has no merged object (abnormal)", merge=_asm_merge_slim(merge_rec)), None
    return None, names


def _asm_resolve_targets(ctx):
    """Resolve the objects to export and compute the gate; returns (err, ctx)."""
    flags = ctx["flags"]
    merge, dry_run = flags["merge"], flags["dry_run"]
    names, objs = [], []
    if merge and dry_run:
        err, names = _asm_merge_targets(ctx)
        if err:
            return err, None
    else:
        if merge:
            err, names = _asm_merge_targets(ctx)
            if err:
                return err, None
        info = _pick_objects(ctx["scope"], ctx["objects"], include_hidden=False)
        if info.get("error"):
            return _err(info["error"], objects=info.get("names"), missing=info.get("missing"),
                        hint="an empty scene/bad arguments must fail; check the object names/collection names"), None
        names = list(info["names"])
        objs = list(info["objects"])
    gate = None
    if merge and isinstance(ctx["merge_rec"].get("gate"), dict):
        gate = ctx["merge_rec"].get("gate")
    elif not (merge and dry_run):
        try:
            raw_g = asm_gate(objects=list(names), manifest=ctx["m"], summary_only=True, strict=True)
            gate = json.loads(raw_g) if isinstance(raw_g, str) else raw_g
        except Exception as e:
            gate = {"ok": False, "verdict": "degraded",
                    "error": "asm_gate raised: %s: %s" % (type(e).__name__, str(e)[:200])}
    ctx.update({"names": names, "objs": objs, "gate": gate})
    return None, ctx
