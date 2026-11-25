// HTTP server config and request stats. PORT/HOST are parsed once at module load, matching the pre-split behaviour.
import { CFG } from '../config.js';
import { parsePortArg } from '../ports.js';
const argv = process.argv.slice(2);
export const PORT = parsePortArg(argv) ?? Number(process.env.VIEWPORT_PORT || CFG.httpPort);
export const HOST = '127.0.0.1';
export const stats = {
    frames: 0,
    acts: 0,
    cmds: 0,
    loops: 0,
    views: 0,
    headless: 0,
    plan: 0,
    worker: 0,
    txn: 0,
    preset: 0,
    job: 0,
    selections: 0,
    lastSelectionMs: null,
    lastPlanMs: null,
    lastViewMs: null,
    lastHeadlessMs: null,
    lastFrameMs: null,
    lastActMs: null,
    lastError: null,
    startedAt: Date.now(),
};
/** v0.9.4: p50/p95 of the latest 20 latencies per route — observation only, never auto-restarts. */
const RTT_N = 20;
export const RTT = {
    frame: [],
    act: [],
    view: [],
    headless: [],
    plan: [],
    worker: [],
    job: [],
};
export function pushRtt(kind, ms) {
    const a = RTT[kind];
    if (!a)
        return;
    const v = Number(ms);
    a.push(Number.isFinite(v) ? Math.round(v) : 0);
    if (a.length > RTT_N)
        a.shift();
}
export function rttView() {
    const out = {};
    for (const k of Object.keys(RTT)) {
        const raw = RTT[k];
        const sorted = raw.slice().sort((x, y) => x - y);
        const q = (p) => sorted.length ? sorted[Math.min(sorted.length - 1, Math.floor(p * sorted.length))] : null;
        out[k] = {
            last: raw.length ? raw[raw.length - 1] : null,
            p50: q(0.5),
            p95: q(0.95),
            n: raw.length,
        };
    }
    return out;
}
/** Per-route request counter (diagnostics: tells whether an old tab is still polling a deleted endpoint) */
export const reqCounts = new Map();
export function bump(p) {
    reqCounts.set(p, (reqCounts.get(p) || 0) + 1);
}
//# sourceMappingURL=config.js.map