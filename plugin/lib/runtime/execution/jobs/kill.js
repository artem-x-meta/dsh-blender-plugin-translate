import { jobSnapshot } from './snapshot.js';
export function jobKill(ctx, id) {
    const key = String(id);
    const j = ctx.jobs.get(key);
    if (j) {
        if (j.status === 'running') {
            j.status = 'killed';
            try {
                if (j.child)
                    j.child.kill('SIGKILL');
            }
            catch (e) {
                /* may have exited already */
            }
        }
        return jobSnapshot(j);
    }
    const r = ctx.ledger.runs.get(key);
    if (r) {
        if (r.status === 'running') {
            r.status = 'killed';
            r.finishedAt = Date.now();
            try {
                if (r.child)
                    r.child.kill('SIGKILL');
            }
            catch (e) {
                /* may have exited already */
            }
            ctx.ledger.ledgerAppend({
                id: key,
                kind: 'headless',
                status: 'killed',
                killedBy: 'op=kill',
                ms: Date.now() - r.startedAt,
            });
        }
        return ctx.ledger.runSnapshot(r);
    }
    const led = ctx.ledger.ledgerList(200).find((x) => x.id === key);
    const rec = led ? ctx.ledger.reconcileLedger(led) : null;
    // v0.9.3: an unknown id **does not throw** — older versions returned unknown, which broke the caller's flow
    return {
        id: key,
        ok: true,
        status: (rec && rec.status) || 'unknown',
        alreadyFinished: !(rec && rec.status === 'running'),
        fromLedger: !!rec,
        note: rec
            ? 'This record comes from the disk ledger; there is no running in-memory handle (already finished, or the backend restarted); no kill needed'
            : 'No record for this id (it may have finished / been cleaned up) — no kill needed; op=list shows current jobs',
    };
}
//# sourceMappingURL=kill.js.map