// shape-search result verdict / restore / suggestions (split out of shape-search.ts, behaviour frozen)
import { KERNEL_BOOTSTRAP } from '../../kernel/index.js';
import { errorMessage } from '../../json.js';
import { pyIndent, pyLit } from './axes.js';
/** Apply the best params back into the scene according to the restore mode */
export async function applyBestParams(E, p, setupSrc, applyBody, poll, board) {
    const best = ((poll.st && poll.st.best) || (board && board.best) || null);
    let applied = null;
    if (best && String(p.restore || 'best') !== 'none' && applyBody) {
        try {
            const body = 'import json as _json\n' +
                'try:\n' +
                pyIndent(setupSrc, '    ') +
                '\n' +
                '    apply(' +
                pyLit(best.params || {}) +
                ')\n' +
                '    print("SEARCH_APPLIED " + _json.dumps({"ok": True, "params": _json.loads(' +
                JSON.stringify(JSON.stringify(best.params || {})) +
                ')}))\n' +
                'except Exception as _e:\n' +
                '    print("SEARCH_APPLIED " + _json.dumps({"ok": False, "error": str(_e)[:200]}))\n';
            const out = await E.addon.send('execute_code', { code: KERNEL_BOOTSTRAP + '\n' + body }, 60000);
            const outRec = (out || null);
            const raw = outRec && typeof outRec.result === 'string' ? outRec.result : '';
            const mm = raw.match(/SEARCH_APPLIED (\{[\s\S]*?\})\s*$/m);
            applied = mm
                ? JSON.parse(mm[1])
                : { ok: false, raw_tail: raw.slice(-200) };
        }
        catch (e) {
            applied = { ok: false, error: errorMessage(e).slice(0, 200) };
        }
    }
    else if (best && String(p.restore || 'best') === 'none') {
        applied = {
            ok: false,
            skipped: true,
            note: 'restore:"none" — the scene stays on the last iteration params; best is in the receipt',
        };
    }
    return { best, applied };
}
export function buildNextSteps(p, objective, best, timedOut) {
    const nextSteps = [];
    if (best)
        nextSteps.push('Recheck through another pathway (the inner loop only optimises the score you wrote): blender_rt_plan(op="qc_render_views", args={views:[…], ref_path:"…"}) + op="audit_measure" + blender_rt_see');
    if (!p.export)
        nextSteps.push('To land a reproducible script: add export:"D:/out/best_fit.py" to this op (or blender_rt_loop(op="export", path=…))');
    if (objective === 'aabb_err')
        nextSteps.push('aabb_err measures only three-axis bounding-box error: it cannot see shape/contour differences, so it must be paired with qc_render_views for image-to-image comparison');
    if (objective !== 'aabb_err')
        nextSteps.push('Single-view contour IoU is necessary but not sufficient (filling the contour alone inflates it) → add clearance/size/feature-line evidence');
    if (timedOut)
        nextSteps.push('wait_ms elapsed and the loop was halted: the results are still there (best/board remain valid); for more iterations raise budget_ms and rerun');
    return nextSteps;
}
export function buildSearchResult(a) {
    const { preview: specEcho, st, timedOut, best, board, pollError, applied, exported, warnings, nextSteps, } = a;
    return {
        ok: !!best,
        op: 'shape_search',
        spec_echo: specEcho,
        stop_reason: (st && st.stop_reason) || (timedOut ? 'wait_timeout' : null),
        timed_out: timedOut,
        iterations_done: st ? st.i : null,
        tps: st ? st.tps : null,
        elapsed_ms: st ? st.elapsed_ms : null,
        best: best,
        board: board ? board.board : null,
        loop_error: st ? st.error : null,
        poll_error: pollError,
        applied: applied,
        exported: exported,
        warnings: warnings,
        next_steps: nextSteps,
        note: 'Declarative search: this op generates a spec and then runs the Blender-side inner loop (bpy.app.timers, GUI sessions only); when the loop ends the scene stays on the last iteration and is handled per the restore mode',
    };
}
//# sourceMappingURL=rank.js.map