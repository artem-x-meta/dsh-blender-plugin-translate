// Job query surface (split out of jobs.ts, behaviour frozen)
import path from 'node:path';
import { winToWsl } from '../../config.js';
import { jobSnapshot, tailFile } from './snapshot.js';
import { startJob } from './start/index.js';
export function jobStart(ctx, opts = {}) {
    const startDeps = {
        E: ctx.E,
        jobs: ctx.jobs,
        ledgerAppend: ctx.ledger.ledgerAppend,
    };
    return startJob(startDeps, opts);
}
export function jobStatus(ctx, id) {
    const key = String(id);
    const j = ctx.jobs.get(key);
    if (j) {
        const s = jobSnapshot(j);
        s.stale = false;
        return s;
    }
    const r = ctx.ledger.runs.get(key);
    if (r) {
        const s = ctx.ledger.runSnapshot(r);
        s.stale = false;
        return s;
    }
    const led = ctx.ledger.ledgerList(200).find((x) => x.id === key);
    return led
        ? Object.assign({ kind: led.kind || 'ledger', fromLedger: true }, ctx.ledger.reconcileLedger(led))
        : {
            id: key,
            status: 'unknown',
            ok: false,
            hint: 'No record for this id (checked both the in-memory ledger and the on-disk ledger)',
        };
}
export function jobCollect(ctx, id, tail = 4000) {
    const key = String(id);
    const j = ctx.jobs.get(key);
    if (j) {
        const snap = jobSnapshot(j);
        const so = tailFile(path.join(j.dir, 'stdout.log'), tail);
        const se = tailFile(path.join(j.dir, 'stderr.log'), tail);
        if (so !== null)
            snap.stdoutTail = so;
        if (se !== null)
            snap.stderrTail = se;
        return snap;
    }
    const r = ctx.ledger.runs.get(key);
    if (r) {
        const snap = ctx.ledger.runSnapshot(r);
        const rLogs = (r.logs || null);
        const soP = rLogs && rLogs.stdoutWsl ? rLogs.stdoutWsl : null;
        const seP = rLogs && rLogs.stderrWsl ? rLogs.stderrWsl : null;
        // v0.9.3: logs are written while a job runs, so a live run can be tailed too (the old collect returned unknown for runs)
        if (soP) {
            const t = tailFile(soP, tail);
            if (t !== null)
                snap.stdoutTail = t;
        }
        if (seP) {
            const t = tailFile(seP, tail);
            if (t !== null)
                snap.stderrTail = t;
        }
        snap.hint = 'run and job share one id space; this entry comes from a synchronous blender_rt_headless run';
        return snap;
    }
    const led = ctx.ledger.ledgerList(200).find((x) => x.id === key);
    if (!led)
        return { id: key, status: 'unknown', ok: false, hint: 'No record for this id; use op=list to see them all' };
    const rec = ctx.ledger.reconcileLedger(led) || {};
    if (rec.status === 'running' || rec.status === 'stale') {
        rec.stdoutTail = rec.stdoutLog ? tailFile(winToWsl(String(rec.stdoutLog)), tail) : null;
        rec.stderrTail = rec.stderrLog ? tailFile(winToWsl(String(rec.stderrLog)), tail) : null;
    }
    return Object.assign({ kind: led.kind || 'ledger', fromLedger: true }, rec);
}
export async function jobWait(ctx, id, timeoutMs = 120000) {
    const key = String(id);
    const budget = Math.max(1000, Math.min(600000, Number(timeoutMs) || 120000));
    const t0 = Date.now();
    let waited = 0;
    for (;;) {
        const st = jobStatus(ctx, key);
        if (st.status !== 'running')
            return Object.assign(jobCollect(ctx, key), { waitedMs: Date.now() - t0, waitTimedOut: false });
        if (Date.now() - t0 >= budget) {
            return Object.assign(jobCollect(ctx, key), {
                waitedMs: Date.now() - t0,
                waitTimedOut: true,
                hint: 'Wait window elapsed and the task is **still running** (not a failure): call op=wait again, or op=collect to see stage/idleMs',
            });
        }
        await new Promise((r2) => setTimeout(r2, 500));
        waited++;
        if (waited > 2400)
            break; // Safety cap (extreme runs over 20min)
    }
    return Object.assign(jobCollect(ctx, key), { waitedMs: Date.now() - t0, waitTimedOut: true });
}
export function jobList(ctx) {
    const mem = Array.from(ctx.jobs.values())
        .map(jobSnapshot)
        .concat(Array.from(ctx.ledger.runs.values()).map((r) => ctx.ledger.runSnapshot(r)));
    const ids = new Set(mem.map((x) => x.id));
    const disk = ctx.ledger
        .ledgerList(60)
        .filter((x) => !ids.has(x.id))
        .map((x) => Object.assign({ kind: x.kind || 'ledger', fromLedger: true }, ctx.ledger.reconcileLedger(x)));
    return mem.concat(disk);
}
//# sourceMappingURL=api.js.map