import { attachPaths } from '../../utils/image.js';
import { headlessReceipt, promotedReceipt, startJobThenMaybeWait, } from '../../headless/receipts/index.js';
import { asArray, asRecord, text } from '../../contracts/dynamic.js';
const LF = String.fromCharCode(10);
export async function runAsJob(port, body, waitS, asJob, serverBudget, autoJobMs) {
    const r2 = await startJobThenMaybeWait(port, body, waitS);
    if (r2.text)
        return { text: text(r2.text) };
    const why = asJob
        ? 'as_job=true'
        : 'estimated budget ' +
            String(Math.round(serverBudget / 1000)) +
            's >= DSH_HEADLESS_AUTO_JOB_MS=' +
            String(autoJobMs) +
            'ms';
    if (r2.finished && r2.job)
        return headlessReceipt(r2.job, {
            mode: 'job',
            jobId: text(r2.jobId),
            notes: ['already backgrounded and finished within the wait window (' + why + ') — this is the complete result, there is no need to collect again'],
        });
    return promotedReceipt(r2.job, text(r2.jobId), why + ': already backgrounded, it did not finish within the wait window (**not a failure**)');
}
export function missingResultText(res, body) {
    const keys = Object.keys(res || {}).filter((k) => k.indexOf('__') !== 0);
    const raw = String((res && res.raw) || '').slice(0, 2000);
    const lines = [
        'HEADLESS result is missing fields (this is not a "failure") · HTTP ' +
            String(res.__status) +
            ' · keys the backend returned: ' +
            (keys.length ? keys.join(', ') : '(empty)'),
    ];
    if (Number(res.__heartbeats) > 0)
        lines.push('(streaming receipt: ' + String(res.__heartbeats) + ' heartbeats, but no result line was obtained)');
    if (raw)
        lines.push('--- raw response (first 2KB) ---' + LF + raw);
    if (body.script)
        lines.push('script content length=' + String(String(body.script).length) + ' characters (the content is in the backend temporary script directory)');
    lines.push('expected log: ' + String(body.outdir || '(default working directory)') + '\\dsh_headless_*.stdout.log');
    lines.push('follow-up: blender_viewport(op="status") to see the runs ledger (since v0.8.10 every headless run has an id/pid/log/artifacts).');
    return { text: lines.join(LF) };
}
export function syncReceipt(bodyRes, res) {
    const out = headlessReceipt(bodyRes, { mode: 'sync', jobId: null, notes: [] });
    // v0.8.9 boundary hint: this run used the streaming receipt (>15 s, N heartbeats)
    const beats = Number((res && res.__heartbeats) || 0);
    if (beats > 0)
        out.text += LF + '(this run took > 15 s, so the backend used the streaming receipt: the result arrived after ' + String(beats) + ' heartbeats)';
    return out;
}
export async function attachShots(ctx, out, args) {
    const shots = asRecord(out.envelope.shots);
    const rows = asArray(shots.rows);
    const paths = rows.map((x) => text(asRecord(x).path)).filter(Boolean);
    const wantSheet = String(args.attach_images) === 'sheet';
    const picked = wantSheet ? [] : paths.filter((p) => !/sheet|montage/i.test(p)).slice(0, 3);
    const att = await attachPaths(ctx, picked, 'headless-shot', wantSheet ? 1 : 3);
    if (att.failed.length)
        out.text += LF + '⚠ image attach failed: ' + att.failed.slice(0, 2).join(' · ');
    if (!att.images.length)
        out.text +=
            LF + '(attach_images is on, but there was no image to attach or reading failed; use read_image(path) on the shots paths)';
    return att.images;
}
//# sourceMappingURL=receipt.js.map
