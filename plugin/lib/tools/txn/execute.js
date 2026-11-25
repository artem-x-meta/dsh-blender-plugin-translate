/** txn execution layer: argument narrowing → POST /txn → text rendering. */
import { ensureBackend } from '../../host/backend/index.js';
import { backendPost, leasedText } from '../../host/http.js';
import { asRecord, text } from '../../contracts/dynamic.js';
import { toolError } from '../errors.js';
import { formatTxn } from './response.js';
export async function executeTxn(port, args) {
    if (!(await ensureBackend(port)))
        return toolError('backend_unreachable', 'backend unavailable (127.0.0.1:' + String(port) + ')', 'start the backend with blender_viewport op=start, then retry');
    const op = text(args.op) || 'list';
    const a = buildTxnArgs(args);
    const r = await backendPost(port, '/txn', { op: op, args: a }, 300000);
    const lt = leasedText(r);
    if (lt)
        return { text: lt };
    if (!r || r.ok !== true)
        return toolError('backend_error', 'TXN ' + op + ' failed · ' + text(r.error || r.raw || 'unknown'), 'use blender_rt_txn op=list to see snapshots');
    return { text: formatTxn(op, asRecord(r.result)) };
}
function buildTxnArgs(args) {
    const a = {};
    if (args.label)
        a.label = text(args.label);
    if (args.note)
        a.note = text(args.note);
    if (args.keep)
        a.keep = Number(args.keep);
    if (args.into)
        a.into = text(args.into);
    if (typeof args.backup === 'boolean')
        a.backup = args.backup;
    if (args.objects)
        a.objects = text(args.objects)
            .split(',')
            .map((s) => s.trim())
            .filter(Boolean);
    return a;
}
//# sourceMappingURL=execute.js.map