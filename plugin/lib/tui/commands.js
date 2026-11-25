import { asArray, asRecord, text } from '../contracts/dynamic.js';
import { NL } from './constants.js';
import { footerField } from './footer.js';
import { getJson } from './http.js';
export const SUBCOMMANDS = [
    { name: 'status', description: 'Blender channel status (zero Blender round-trips)' },
    { name: 'doctor', description: 'health-check the GUI channel (runs one real bpy round-trip)' },
    { name: 'jobs', description: 'headless job list' },
];
function ago(ms) {
    if (ms == null)
        return 'never';
    const s = Math.round(Number(ms) / 1000);
    return s < 60 ? String(s) + ' s ago' : String(Math.round(s / 60)) + ' min ago';
}
/** '/blender <sub>' → text. Exported for self-checks. */
export async function blenderCommand(rawInput, opts, signal) {
    const sub = String(rawInput || '')
        .trim()
        .split(/\s+/)[0] || 'status';
    const port = opts.port;
    if (sub === 'status') {
        const st = await getJson(port, '/host/state', signal);
        const f = footerField(st, opts.holder, port);
        if (!st || st.ok !== true)
            return { kind: 'success', text: f.text + NL + f.detail };
        const ch = asRecord(st.channel);
        const lease = asRecord(st.lease);
        const lines = [
            f.text + ' — ' + f.detail,
            'Channel: last success ' +
                ago(ch.lastOkAgeMs) +
                ' · in flight ' +
                String(ch.inflight || 0) +
                ' · last command ' +
                (text(ch.lastCmd) || '-'),
            'Lease: ' +
                (lease.active
                    ? text(lease.holder) + (lease.holder === opts.holder ? ' (this session)' : '')
                    : 'idle'),
            'Render: ' +
                (asRecord(st.render).busy
                    ? 'in progress (' + ago(asRecord(st.render).ageMs).replace(' ago', '') + ')'
                    : 'none'),
            'Jobs: ' + String(asRecord(st.jobs).running || 0) + ' running',
        ];
        if (ch.lastError)
            lines.push('Last error (' + ago(ch.lastErrorAgeMs) + '): ' + text(ch.lastError));
        return { kind: 'success', text: lines.join(NL) };
    }
    if (sub === 'doctor') {
        const d = await getJson(port, '/doctor', signal, 30000);
        if (!d)
            return {
                kind: 'error',
                text: 'Health check failed: backend unreachable (127.0.0.1:' +
                    String(port) +
                    ') · have the model run blender_viewport(op="start")',
            };
        const a = asRecord(d.addon);
        const lines = ['Diagnosis: ' + (text(a.kind) || (d.ok ? 'ok' : 'unknown'))];
        if (a.summary)
            lines.push('Conclusion: ' + text(a.summary));
        if (a.fix)
            lines.push('Fix: ' + text(a.fix));
        return { kind: d.ok ? 'success' : 'error', text: lines.join(NL) };
    }
    if (sub === 'jobs') {
        const j = await getJson(port, '/host/jobs?limit=10', signal);
        if (!j || j.ok !== true)
            return { kind: 'error', text: 'Failed to fetch the job list: backend unreachable (127.0.0.1:' + String(port) + ')' };
        const jobs = asArray(j.jobs);
        if (!jobs.length)
            return { kind: 'success', text: 'no headless jobs' };
        const lines = [
            'Jobs: ' + String(j.running || 0) + ' running / ' + String(j.total || jobs.length) + ' total:',
        ];
        for (const job of jobs) {
            const rec = asRecord(job);
            lines.push('  ' +
                (text(rec.id) || '?') +
                ' · ' +
                (text(rec.status) || '?') +
                ' · ' +
                String(Math.round(Number(rec.ms || 0) / 1000)) +
                ' s' +
                (rec.script ? ' · ' + (text(rec.script).split(/[\\/]/).pop() ?? '') : ''));
        }
        return { kind: 'success', text: lines.join(NL) };
    }
    return {
        kind: 'error',
        text: 'Unknown subcommand "' + sub + '": available ' + SUBCOMMANDS.map((s) => s.name).join(' / '),
    };
}
//# sourceMappingURL=commands.js.map