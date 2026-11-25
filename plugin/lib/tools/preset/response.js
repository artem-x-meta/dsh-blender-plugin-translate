/** preset response text: summary rendering for list and apply. */
import { asArray, asRecord, text } from '../../contracts/dynamic.js';
const NL = String.fromCharCode(10);
export function formatPreset(op, res) {
    const parts = [];
    parts.push('PRESET ' + op + ' ok');
    if (op === 'list') {
        const presets = asArray(res.presets).map((row) => {
            const p = asRecord(row);
            return { name: text(p.name), kind: text(p.kind), keys: Number(p.keys ?? 0) };
        });
        parts.push('Total ' +
            String(res.count ?? presets.length) +
            ' presets: ' +
            presets.map((p) => p.name + '(' + p.kind + ',' + String(p.keys) + ' keys)').join(' · '));
        parts.push('Directory: ' + text(res.dir));
    }
    else if (op === 'apply') {
        const rr = asRecord(res.report);
        const applied = asArray(rr.applied);
        const skipped = asArray(rr.skipped);
        const errors = asArray(rr.errors);
        parts.push('Preset ' +
            text(res.preset) +
            ' · targets ' +
            JSON.stringify(res.targets) +
            ' · applied ' +
            String(applied.length) +
            ' entries');
        if (skipped.length)
            parts.push('Skipped: ' + JSON.stringify(skipped).slice(0, 300));
        if (errors.length)
            parts.push('Errors: ' + JSON.stringify(errors).slice(0, 300));
    }
    else
        parts.push(JSON.stringify(res).slice(0, 900));
    return parts.join(NL);
}
//# sourceMappingURL=response.js.map