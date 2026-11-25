/** txn response text: renders the per-op summary for snapshot/restore/list/mark/revert. */
import { asArray, asRecord, text } from '../../contracts/dynamic.js';
const NL = String.fromCharCode(10);
export function formatTxn(op, res) {
    const parts = [];
    parts.push('TXN ' + op + ' ok');
    const snapshot = asRecord(res.snapshot);
    if (op === 'snapshot' && res.snapshot)
        parts.push('snapshot ' +
            text(snapshot.label) +
            ' · ' +
            text(snapshot.bytes) +
            'B · ' +
            text(snapshot.ms) +
            'ms · ' +
            text(snapshot.objects) +
            ' objects' +
            NL +
            'path: ' +
            text(snapshot.path));
    else if (op === 'restore')
        parts.push('restored: ' + JSON.stringify(res.restored || {}).slice(0, 200) + NL + text(res.warning));
    else if (op === 'list') {
        const snapshots = asArray(res.snapshots);
        parts.push('snapshots: ' +
            String(snapshots.length) +
            ' entries: ' +
            snapshots
                .map((raw) => {
                const s = asRecord(raw);
                return text(s.label) + '(' + text(s.bytes) + 'B)';
            })
                .join(' · '));
        parts.push('mark: ' + JSON.stringify(res.marks || []));
        parts.push('directory: ' + text(res.snapshot_dir));
    }
    else if (op === 'mark')
        parts.push('mark recorded ' + text(res.mark) + ' · ' + text(res.objects) + ' objects');
    else if (op === 'revert') {
        const blocked = asArray(res.blocked);
        parts.push('reverted ' +
            text(res.reverted) +
            ': changed ' +
            text(res.changed_count) +
            ' objects' +
            (blocked.length ? ' · skipped ' + JSON.stringify(blocked).slice(0, 200) : ''));
    }
    else
        parts.push(JSON.stringify(res).slice(0, 800));
    return parts.join(NL);
}
//# sourceMappingURL=response.js.map