import { backendPost } from '../host/http.js';
import { attachPaths, planImagePaths } from '../utils/image.js';
import { redactSecrets } from '../tools/errors.js';
import { asRecord, isRecord, text } from '../contracts/dynamic.js';
import { PLAN_HEADLESS_ALIAS, PLAN_HEADLESS_MAP } from './routes.generated.js';
export { PLAN_HEADLESS_ALIAS, PLAN_HEADLESS_MAP };
export function planHeadlessTarget(op) {
    const o = String(op || '');
    const alias = PLAN_HEADLESS_ALIAS[o];
    if (alias)
        return { api: alias[0], sub: alias[1], preload: alias[2] };
    // The generated worker table owns the ordering: exact aliases first, then prefix
    // rows by precedence. qc_render_ is rank 8, ahead of qc_ (rank 17), which keeps the
    // fix for headless qc_render_*: the worker serves dsh_qc_render_api and has no
    // GUI flat-exec fallback, so the more specific prefix must win. Strip lengths also
    // come from config/routing.json rather than being repeated here.
    for (const row of PLAN_HEADLESS_MAP) {
        const p = row[0];
        if (o.indexOf(p) === 0)
            return { api: row[1], sub: o.slice(row[3]), preload: row[2] };
    }
    return null;
}
/** Execute one plan op with the persistent worker (does not depend on the GUI addon; modules are injected into K by preload) */
export async function planViaWorker(ctx, port, op, payload, session) {
    const t = planHeadlessTarget(op);
    if (!t)
        return { ok: false, error: 'this plan op has no headless mapping (check op="catalog" first, or use the GUI channel)' };
    const nm = session ? String(session) : 'plan-' + String(t.api).replace(/^dsh_|_api$/g, '');
    try {
        const st = await backendPost(port, '/worker', {
            op: 'start',
            name: nm,
            preload: t.preload,
            engine: 'workbench',
            warmup: false,
            isolated: true,
        }, 120000);
        if (st.ok !== true)
            return {
                ok: false,
                error: 'headless worker start failed: ' + text(st.error || st.raw || 'unknown'),
            };
        const code = 'import json as _json\n_s = _json.dumps(_json.loads(' +
            JSON.stringify(JSON.stringify(payload || {})) +
            '))\n' +
            '_r = K.' +
            t.api +
            '["dispatch"](' +
            JSON.stringify(String(t.sub)) +
            ', _s)\n' +
            'print("HEADLESS " + (_r if isinstance(_r, str) else _json.dumps(_r, ensure_ascii=False)))';
        const r = await backendPost(port, '/worker', { op: 'exec', name: nm, code: code, isolated: true }, 900000);
        const rr = asRecord(r.result);
        if (r.ok !== true) {
            return {
                ok: false,
                error: 'headless plan execution failed: ' + text(r.error || rr.error || 'unknown'),
                hint: redactSecrets(rr.traceback || '').slice(-1200),
            };
        }
        return { ok: true, res: rr.result, via: 'worker:' + nm };
    }
    catch (e) {
        return { ok: false, error: 'headless plan exception: ' + redactSecrets(e) };
    }
}
/** Unified plan receipt wrap-up: envelope + attached images (shared by the GUI and headless paths) */
export async function finishPlanResponse(ctx, op, res, argsIn) {
    const txt = typeof res === 'string' ? res : String(JSON.stringify(res, null, 1) ?? '');
    const CAP = 12000;
    const env = planEnvelope(op, res);
    const args = asRecord(argsIn);
    const attachWanted = args.attach_images !== undefined
        ? !!args.attach_images
        : [
            'img_digest',
            'qc_compare',
            'visualreport_report',
            'qc_visual_report',
            'shapesolve_solve',
        ].indexOf(op) >= 0;
    let images = [];
    let attachNote = '';
    if (attachWanted) {
        const att = await attachPaths(ctx, planImagePaths(res), 'plan-' + op.replace(/[^a-z0-9_]+/gi, '_'), 2);
        images = att.images;
        if (att.used.length)
            attachNote =
                String.fromCharCode(10) +
                    'images attached: ' +
                    String(att.used.length) +
                    ' (' +
                    att.used.join(' · ') +
                    ')';
        if (att.failed.length)
            attachNote += String.fromCharCode(10) + '⚠ some images were not attached: ' + att.failed.slice(0, 2).join(' · ');
    }
    const head = 'PLAN ' +
        op +
        ' ok · ' +
        String(txt.length) +
        ' chars · verdict=' +
        text(env.verdict) +
        (env.summary ? ' · ' + text(env.summary) : '') +
        attachNote +
        String.fromCharCode(10);
    return {
        text: head +
            (txt.length > CAP
                ? txt.slice(0, CAP) +
                    String.fromCharCode(10) +
                    '…[truncated, ' +
                    String(txt.length) +
                    ' characters total; for the full structured result see the backend results/ directory or write it to disk with headless(outJson=…)]'
                : txt),
        envelope: env,
        ...(images.length ? { images: images } : {}),
    };
}
/** Weak-model contract v2: verdict-first envelope (single line, ≤2k) — the same policy for plan and headless */
export function planEnvelope(op, res) {
    const r = isRecord(res) ? res : { value: res };
    const verdict = r.verdict ||
        r.state ||
        (r.ok === false ? 'fail' : r.ok === true ? (r.clean === false ? 'degraded' : 'pass') : null);
    let defects = [];
    for (const k of ['top_defects', 'offenders', 'defects', 'failures', 'errors']) {
        if (Array.isArray(r[k])) {
            defects = r[k];
            break;
        }
    }
    const limit = (t, n) => text(t).slice(0, n);
    const top = defects.slice(0, 5).map((d, i) => {
        if (!isRecord(d))
            return { id: 'D' + String(i + 1), code: limit(d, 80) };
        return {
            id: d.id || 'D' + String(i + 1),
            code: limit(d.code || d.kind || d.class || d.error || 'issue', 60),
            severity: d.severity || null,
            object: d.object || d.a || d.name || null,
            measured: d.measured ||
                (d.volume_mm3 !== undefined
                    ? { volume_mm3: d.volume_mm3 }
                    : d.depth_mm !== undefined
                        ? { depth_mm: d.depth_mm }
                        : null),
            fix_hint: d.fix_hint || d.repair || null,
        };
    });
    const next = (Array.isArray(r.next) ? r.next : Array.isArray(r.repairs) ? r.repairs : [])
        .slice(0, 3)
        .map((x) => typeof x === 'string'
        ? { op: limit(x, 120) }
        : {
            op: limit(asRecord(x).op || asRecord(x).name || 'next', 80),
            args: asRecord(x).args || null,
            why: limit(asRecord(x).why || '', 120),
        });
    const env = {
        contract: 'receipt.v2',
        op: op,
        verdict: verdict,
        summary: limit(r.summary || r.note || r.error || r.hint || '', 160),
        top_defects: top,
        next: next,
        images: planImagePaths(r).slice(0, 2),
        provenance: { ms: typeof r.ms === 'number' ? r.ms : null },
    };
    const counts = r.counts || (r.totals ? r.totals : null);
    if (isRecord(counts))
        env.counts = counts;
    if (isRecord(r.detail))
        env.detail = {
            path: r.detail.path || null,
            bytes: r.detail.bytes || null,
            id: r.detail.id || null,
        };
    // envelope hard budget: past 2k keep only the three most useful parts (verdict / top3 / next2)
    try {
        if (JSON.stringify(env).length > 2000) {
            env.top_defects = top.slice(0, 3);
            env.next = next.slice(0, 2);
            delete env.counts;
            const detail = asRecord(env.detail);
            if (detail.bytes && Number(detail.bytes) > 0) {
                /* keep path only */
            }
            else
                delete env.detail;
        }
    }
    catch {
        /* ignore */
    }
    return env;
}
//# sourceMappingURL=headless-target.js.map
