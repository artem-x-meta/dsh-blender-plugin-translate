// Run ledger (in-memory runs + disk JSONL + writability self-check): split out from ledger.ts
import path from 'node:path';
import { winToWsl } from '../../config.js';
import { WIN_TMP, WSL_TMP } from '../../paths.js';
import fs from 'node:fs';
import { errorCode, errorMessage } from '../../core/json.js';
import { PLUGIN_VERSION } from '../../core/evidence.js';
export function createLedgerStore() {
    const runs = new Map();
    const LEDGER = path.join(winToWsl(WIN_TMP), 'jobs', 'index.jsonl');
    // ---- v0.9.3 (same origin): workDir writability — in older versions ledger/log write failures were **silent**
    // (measured: when workDir sits on a read-only mount, not one disk ledger record can be written, while op=list/status only says "no records").
    let ledgerWarn = null;
    let workdirProbeCache = null;
    function workdirProbe() {
        if (workdirProbeCache)
            return workdirProbeCache;
        const out = { wsl: WSL_TMP, win: WIN_TMP, writable: false, error: null };
        try {
            fs.mkdirSync(WSL_TMP, { recursive: true });
            const probe = path.join(WSL_TMP, '.dsh_write_probe_' + process.pid);
            fs.writeFileSync(probe, 'ok', 'utf8');
            fs.unlinkSync(probe);
            out.writable = true;
        }
        catch (e) {
            out.error = errorCode(e) || errorMessage(e).slice(0, 200);
        }
        workdirProbeCache = out;
        return out;
    }
    function ledgerAppend(rec) {
        try {
            fs.mkdirSync(path.dirname(LEDGER), { recursive: true });
            fs.appendFileSync(LEDGER, JSON.stringify(Object.assign({ pluginVersion: PLUGIN_VERSION, at: Date.now() }, rec)) +
                String.fromCharCode(10), 'utf8');
            ledgerWarn = null;
        }
        catch (e) {
            // Silent failure is exactly what this version eliminates: record it so /status and op=list can report it
            ledgerWarn = {
                path: LEDGER,
                error: errorCode(e) || errorMessage(e).slice(0, 200),
                hint: 'workDir is not writable → disk ledger/logs cannot be written (in-memory ledger and artifacts are unaffected). Change workDir in dsh-blender.config.json or DSH_BLENDER_WORKDIR to a directory writable on both sides (a WSL path works too, e.g. /home/<user>/dsh-blender-work).',
            };
        }
    }
    function ledgerState() {
        const p = workdirProbe();
        return {
            path: LEDGER,
            writable: !!p.writable && !ledgerWarn,
            workDir: p,
            lastError: ledgerWarn ? ledgerWarn.error : p.writable ? null : p.error,
            hint: ledgerWarn
                ? ledgerWarn.hint
                : p.writable
                    ? null
                    : 'workDir is not writable (' +
                        String(p.error) +
                        '): ledger/logs will fail silently — switch to a writable workDir (a WSL path works too).',
        };
    }
    function ledgerList(limit = 40) {
        try {
            const lines = fs
                .readFileSync(LEDGER, 'utf8')
                .trim()
                .split(String.fromCharCode(10))
                .filter(Boolean)
                .slice(-limit * 4);
            const by = new Map();
            for (const l of lines) {
                try {
                    const o = JSON.parse(l);
                    const id = String(o.id);
                    by.set(id, Object.assign(by.get(id) || {}, o));
                }
                catch (e) {
                    /* skip */
                }
            }
            return Array.from(by.values())
                .sort((a, b) => (Number(b.startedAt) || 0) - (Number(a.startedAt) || 0))
                .slice(0, limit);
        }
        catch (e) {
            return [];
        }
    }
    return { runs, LEDGER, ledgerAppend, ledgerState, ledgerList };
}
//# sourceMappingURL=state.js.map