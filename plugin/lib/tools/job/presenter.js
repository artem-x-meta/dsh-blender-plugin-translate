/** Presentation layer for blender_rt_job: job list/various receipt assembly (behaviour identical to v2.6.2). */
import { headlessReceipt, promotedReceipt } from '../../headless/receipts/index.js';
import { clipText, safeStringify } from '../../ui/cards.js';
import { asArray, asRecord, text } from '../../contracts/dynamic.js';
const LF = String.fromCharCode(10);
export function renderJobList(r) {
    const js = asArray(r.jobs);
    if (!js.length)
        return { text: 'no jobs' };
    const lines = js.map((raw) => {
        const j = asRecord(raw);
        const artifacts = asArray(j.artifacts);
        return ('  ' +
            text(j.id) +
            ' · ' +
            text(j.status) +
            (j.stageName ? ' · stage=' + text(j.stageName) : '') +
            (typeof j.ms === 'number' ? ' · ' + String(Math.round(j.ms / 1000)) + 's' : '') +
            (j.fromLedger ? ' · (disk ledger)' : '') +
            ' · artifacts ' +
            String(artifacts.length) +
            ' items');
    });
    return {
        text: 'jobs (' + String(js.length) + '): ' + LF + lines.join(LF),
    };
}
export function buildJobStart(j, ctx) {
    ctx.notes.push('moved to background (pid ' + text(j.pid) + ', log dir ' + text(j.logDir) + ')');
    ctx.hint =
        'Use op=wait id=' +
            text(j.id) +
            ' to block until the result, or op=collect for progress (stage/idleMs); op=kill aborts';
    const out = promotedReceipt(j, text(j.id), 'op=start accepted');
    out.envelope.mode = 'job-start';
    out.envelope.notes = ctx.notes;
    out.envelope.hint = ctx.hint;
    return out;
}
export function buildJobKill(j) {
    const t = j.alreadyFinished || j.status === 'unknown'
        ? 'JOB kill · ' +
            text(j.id) +
            ' · ' +
            text(j.status) +
            ' (' +
            text(j.note || 'already finished/does not exist, no kill needed') +
            ')'
        : 'JOB kill · ' + text(j.id) + ' · status=' + text(j.status) + ' (SIGKILL sent)';
    return {
        text: t,
        envelope: {
            kind: 'job',
            mode: 'job-kill',
            id: j.id || null,
            status: j.status || null,
            ok: true,
            alreadyFinished: !!j.alreadyFinished,
            note: j.note || null,
            fromLedger: !!j.fromLedger,
        },
    };
}
export function buildRecoveredJob(j, op) {
    return {
        text: 'JOB ' +
            op +
            ' · ' +
            text(j.id) +
            ' · status=' +
            text(j.status) +
            LF +
            '(completed · disk artifacts reconciled, recovered from ' +
            text(j.recoveredFrom || '?') +
            ')' +
            LF +
            text(j.hint),
        envelope: {
            kind: 'job',
            mode: 'job-' + op,
            id: j.id || null,
            status: j.status || null,
            ok: true,
            recovered: true,
            recoveredFrom: j.recoveredFrom || null,
            recoveredEvidence: j.recoveredEvidence || null,
            resultJson: j.resultJson || null,
            resultPath: j.resultPath || null,
            stdoutTail: clipText(j.stdoutTail, 1000, 1000),
        },
    };
}
export function buildLedgerJob(j, op) {
    return {
        text: 'JOB ' +
            op +
            ' · ' +
            text(j.id) +
            ' · status=' +
            text(j.status) +
            LF +
            '(disk ledger entry)' +
            text(j.staleReason) +
            LF +
            text(j.hint),
        envelope: {
            kind: 'ledger',
            mode: 'job-' + op,
            id: j.id || null,
            status: j.status || null,
            ok: true,
            fromLedger: true,
            staleReason: j.staleReason || null,
            pid: j.pid || null,
            pidAlive: !!j.pidAlive,
            resultJson: j.resultJson || null,
            resultPath: j.resultPath || null,
            stdoutTail: clipText(j.stdoutTail, 1000, 1000),
        },
    };
}
export function buildCollectRunning(j, ctx) {
    const hb = asRecord(j.heartbeat);
    const at = Number(hb.at || 0);
    ctx.notes.push('the job is still running (not a failure): stage=' +
        safeStringify(j.stage || j.stageName) +
        (j.progress ? ' · progress=' + safeStringify(j.progress) : '') +
        (j.heartbeat ? ' · heartbeat ' + String(Math.round((Date.now() - at || 0) / 1000)) + 's ago' : '') +
        ' · last output ' +
        String(Math.round(Number(j.idleMs || 0) / 1000)) +
        's ago');
    const out = promotedReceipt(j, text(j.id), 'op=collect: the job is still running');
    out.envelope.mode = 'collect-running';
    out.envelope.notes = ctx.notes;
    return out;
}
export function buildWaitTimeout(j) {
    const out = promotedReceipt(j, text(j.id), 'op=wait: the wait window (' +
        String(Math.round(Number(j.waitedMs || 0) / 1000)) +
        's) expired, the job is still running');
    out.envelope.mode = 'wait-timeout';
    return out;
}
export function buildFinalJob(j, ctx, notes) {
    return headlessReceipt(j, {
        mode: 'job',
        jobId: ctx.jobId,
        runId: ctx.runId,
        notes: notes,
    });
}
//# sourceMappingURL=presenter.js.map
