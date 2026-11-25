// trajectory recorder (split out of trajectory.ts, behavior frozen)
import path from 'node:path';
import fs from 'node:fs';
function trajShortHash(s) {
    let h = 0;
    for (let i = 0; i < s.length; i++)
        h = (h * 31 + s.charCodeAt(i)) | 0;
    return (h >>> 0).toString(16).padStart(8, '0');
}
export function trajRecord(deps, route, op, args, ms, ok, err, extra) {
    if (deps.TRAJ_OFF)
        return;
    // v0.9.6: add family / args_keys / hint_shown -- used for "family coverage" and "intent→tool" weekly reports.
    // family only makes sense for the plan route (frame's "op" is really the size, act's "op" is a code snippet; splitting those is noise).
    const fam = route === 'plan' && op ? String(op).split('_')[0] : null;
    try {
        fs.mkdirSync(deps.TRAJ_DIR, { recursive: true });
        const d = new Date();
        const key = String(d.getFullYear()) +
            String(d.getMonth() + 1).padStart(2, '0') +
            String(d.getDate()).padStart(2, '0');
        const f = path.join(deps.TRAJ_DIR, 'blender_rt-' + key + '.jsonl');
        try {
            const st = fs.statSync(f);
            if (st.size > deps.TRAJ_MAX_BYTES)
                fs.renameSync(f, path.join(deps.TRAJ_DIR, 'blender_rt-' + key + '-' + Date.now() + '.jsonl'));
        }
        catch (e) {
            /* first write */
        }
        const s = args === undefined || args === null
            ? ''
            : typeof args === 'string'
                ? args
                : JSON.stringify(args);
        fs.appendFileSync(f, JSON.stringify({
            t: d.toISOString(),
            route: route,
            op: op === undefined || op === null ? null : String(op),
            ms: ms,
            ok: !!ok,
            err: err ? String(err).slice(0, 300) : null,
            args_bytes: s.length,
            args_digest: trajShortHash(s),
            args_head: s ? s.slice(0, deps.TRAJ_FULL ? 8000 : 300) : null,
            // v0.9.6: lets "family coverage" and "parameter-key distribution" be counted (values are not recorded, only key names)
            family: fam,
            args_keys: args && typeof args === 'object' && !Array.isArray(args)
                ? Object.keys(args).slice(0, 20)
                : null,
            hint_shown: !!(extra !== null &&
                typeof extra === 'object' &&
                extra.hint_shown),
        }) + String.fromCharCode(10), 'utf8');
    }
    catch (e) {
        /* the trajectory is a side channel: on error just drop this line */
    }
}
//# sourceMappingURL=record.js.map