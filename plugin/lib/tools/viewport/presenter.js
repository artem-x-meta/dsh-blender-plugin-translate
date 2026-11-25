/** blender_viewport's presentation layer: formats backend receipts into model-readable text (it changes no verdict). */
import { HERE, HOLDER, HOST_API, PLUGIN_VERSION } from '../../constants.js';
import { schemaResolve } from '../../contracts/tool.js';
import { asArray, asRecord, text } from '../../contracts/dynamic.js';
import { base, childAlive, getChild, isPaused } from '../../host/backend/index.js';
import { tuiHostSummary } from '../../tui/index.js';
const NL = String.fromCharCode(10);
// Separate "timeout/aborted" from "connection refused" — the former means the addon/bpy round-trip never answered, only the latter means the backend never started.
const TIMEOUT_RE = /timeout|timed out|aborted|abort/i;
// Connection-level failure: a TCP connect timeout (ETIMEDOUT / connect timeout) means **cannot connect**,
// not "the backend is up, the round-trip is just slow" → this must be decided before timeout (the order in formatStatusError is the contract).
const CONN_RE = /ECONNREFUSED|ECONNRESET|EHOSTUNREACH|ENOTFOUND|ETIMEDOUT|connect timeout|fetch failed|socket hang up/i;
// While Blender is rendering, main-thread commands first get BUSY_RENDER (engine/lifecycle.ts) — that is "waiting for the render", not a broken addon.
const BUSY_RE = /BUSY_RENDER/i;
const MAX_CAUSE_DEPTH = 4;
export function renderViewportOutput(_args, value) {
    return [{ type: 'text', text: String(value) }];
}
export function formatWho(raw) {
    const w = asRecord(raw);
    const lz = asRecord(w.lease);
    const m = asRecord(w.metrics);
    return [
        'Lease: ' +
            (lz.active
                ? 'holder ' +
                    text(lz.holder) +
                    ' (remaining ' +
                    String(Math.round(Number(lz.expiresInMs || 0) / 1000)) +
                    's, renewed ' +
                    text(lz.renewals || 0) +
                    ' times)'
                : 'idle (anyone may write)'),
        'this session holder: ' + HOLDER + (lz.active && lz.holder === HOLDER ? ' (this very session)' : ''),
        'write scope: ' + (lz.scope ? JSON.stringify(lz.scope) : 'undeclared (= no restriction)'),
        'channel: calls=' +
            text(m.calls || 0) +
            ' errors=' +
            text(m.errors || 0) +
            ' timeouts=' +
            text(m.timeouts || 0) +
            ' inflight=' +
            text(m.inflight || 0) +
            ' lastCmd=' +
            text(m.lastCmd || '-'),
        'stats: ' + JSON.stringify(w.stats || {}),
    ].join(NL);
}
export function formatLeaseResult(op, r) {
    if (op === 'lease' && asRecord(r).error === 'leased') {
        const x = asRecord(r);
        return ('lease is taken: holder=' +
            text(x.holder) +
            ', remaining ' +
            String(Math.round(Number(x.expiresInMs || 0) / 1000)) +
            's' +
            NL +
            text(x.hint) +
            NL +
            '(confirm the other side is running to know why you are blocked; to grab it anyway add force=true)');
    }
    return (op === 'lease' ? 'LEASE ' : 'RELEASE ') + JSON.stringify(r);
}
export function formatLeaseError(op, e) {
    return op + ' failed: ' + errorText(e) + ' (backend not started? blender_viewport op=start)';
}
export function formatLaunch(r) {
    const x = asRecord(r);
    const lines = [];
    lines.push((x.ok ? 'LAUNCH ok' : 'LAUNCH not successful') +
        (x.already ? ' · already listening (idempotent, not started again)' : x.dryRun ? ' · dryRun (not started)' : '') +
        (x.launched ? ' · spawned pid=' + text(x.pid) : '') +
        ' · addon port ' +
        text(x.addonPort || '-') +
        ' · waited ' +
        text(x.waitedMs || 0) +
        'ms');
    if (x.exe)
        lines.push('blender.exe: ' + text(x.exe) + (x.configFrom ? ' (source ' + text(x.configFrom) + ')' : ''));
    if (x.error)
        lines.push('error: ' + text(x.error));
    if (x.hint)
        lines.push('hint: ' + text(x.hint));
    const steps = asArray(x.steps);
    for (const s of steps)
        lines.push('· ' + text(s));
    appendLaunchBootLines(lines, x);
    const doc = asRecord(x.doctor);
    const addon = asRecord(doc.addon);
    if (doc.addon)
        lines.push('health check after launch: ' + (addon.summary ? text(addon.summary) : JSON.stringify(addon)).slice(0, 400));
    if (x.bootScript)
        lines.push('boot script: ' + text(x.bootScript) + ' (run it directly to debug by hand)');
    return lines.join(NL);
}
function appendLaunchBootLines(lines, x) {
    const b = asRecord(x.boot);
    if (x.boot) {
        lines.push('boot verdict (launch-status.json written by the GUI side): loaded_by=' +
            text(b.loaded_by || '-') +
            ' · server_running=' +
            text(b.server_running) +
            ' · enabled=' +
            JSON.stringify(b.enabled || []));
        const bootErrors = asArray(b.errors);
        if (bootErrors.length)
            lines.push('boot errors: ' + bootErrors.slice(0, 4).map(text).join(' | '));
        if (b.env)
            lines.push('boot env: ' + JSON.stringify(b.env));
        const seen = asArray(b.addon_modules_seen);
        if (seen.length)
            lines.push('addon modules visible in the GUI: ' + seen.slice(0, 20).map(text).join(', '));
        return;
    }
    if (x.launched || x.dryRun) {
        lines.push('boot status file: ' +
            text(x.statusFile || '?') +
            ' (not read: maybe Blender has not reached the script yet, or the exe path is wrong)');
    }
}
export function formatDoctor(raw) {
    const d = asRecord(raw);
    const metrics = asRecord(d.metrics);
    const addon = d.addon ? asRecord(d.addon) : null;
    const diag = d.diagnosis ? asRecord(d.diagnosis) : asRecord(metrics.lastDiagnosis);
    const lines = [];
    // when doctor fails, the authoritative verdict lives in d.addon (kind/summary/fix); metrics.lastDiagnosis is only a cached historical probe,
    // and the old code read it first, which showed "AI operation paused" as main-thread-busy.
    lines.push('diagnosis: ' + text((addon && addon.kind) || d.kind || diag.kind || (d.ok ? 'ok' : 'unknown')));
    lines.push('host API: ' + HOST_API); // v0.9.2 (R2): after a DSH upgrade, see at a glance which dsh-tools the plugin is attached to
    lines.push(tuiHostSummary()); // v2.6.1: which seams of the dsh-TUI host half are wired up
    lines.push('plugin: v' + PLUGIN_VERSION + ' @ ' + HERE);
    lines.push('schemastery: ' +
        (schemaResolve.via
            ? 'resolved (' + schemaResolve.via + ')'
            : '❌ ' + String(schemaResolve.error || 'unresolved') + ' — tools not registered (degraded mode)'));
    const summary = addon && addon.summary ? text(addon.summary) : diag.summary ? text(diag.summary) : '';
    const fix = addon && addon.fix ? text(addon.fix) : diag.fix ? text(diag.fix) : '';
    if (summary)
        lines.push('conclusion: ' + summary);
    if (fix)
        lines.push('fix: ' + fix);
    if (addon)
        lines.push('addon: ' + JSON.stringify(addon));
    if (!d.ok && d.error && !addon)
        lines.push('error: ' + text(d.error));
    const ledger = d.ledger ? asRecord(d.ledger) : null;
    const workDir = ledger ? asRecord(ledger.workDir) : null;
    if (ledger)
        lines.push('work dir: ' +
            text(workDir?.wsl || '?') +
            (workDir?.writable
                ? ' (writable)'
                : ' (⚠️ **not writable** — ' + text(ledger.lastError || '?') + ')'));
    if (ledger && !ledger.writable && ledger.hint)
        lines.push('fix: ' + text(ledger.hint));
    lines.push('counts: ' + JSON.stringify(d.stats || {}));
    lines.push('metrics: calls=' +
        text(metrics.calls || 0) +
        ' errors=' +
        text(metrics.errors || 0) +
        ' timeouts=' +
        text(metrics.timeouts || 0) +
        ' inflight=' +
        text(metrics.inflight || 0) +
        ' lastCmd=' +
        text(metrics.lastCmd || '-') +
        (metrics.lastCmdAgeMs === null || metrics.lastCmdAgeMs === undefined
            ? ''
            : ' (' + String(Math.round(Number(metrics.lastCmdAgeMs) / 1000)) + 's ago)') +
        ' views=' +
        text(metrics.views || 0) +
        ' headlessRuns=' +
        text(metrics.headlessRuns || 0));
    return lines.join(NL);
}
export function formatStatus(port, raw) {
    const s = asRecord(raw);
    const region = s.region ? asRecord(s.region) : null;
    const views = region ? asArray(region.views) : [];
    const v = views.length ? asRecord(views[0]) : null;
    const ledger = s.ledger ? asRecord(s.ledger) : null;
    const plugin = s.plugin ? asRecord(s.plugin) : null;
    const runs = asArray(s.runs);
    const child = getChild();
    const payload = {
        running: true,
        paused: isPaused(),
        child: child
            ? childAlive()
                ? 'alive pid=' + String(child.pid)
                : 'dead pid=' + String(child.pid)
            : 'none',
        watchdog: '15s',
        endpoint: base(port),
        viewportRegion: v ? v.region : null,
        shading: v ? v.shading : null,
        window: region ? region.window : null,
        stats: s.stats,
        diagnosis: s.diagnosis || null,
        addonError: s.addonError || null, // v0.9.3: local info (ledger/work dir) must be visible even when the addon is not connected
        plugin: s.plugin || null, // v0.8.10: in-process lib version + runtime fingerprint
        pluginVersion: plugin ? plugin.version : null,
        hostApi: HOST_API, // v0.9.2 (R2): the host dsh-tools the plugin side resolved
        toolVersion: PLUGIN_VERSION,
        // v1.0.1 (issue #10): which channel package-name-form resolution went through / why it failed — this kind of silent wholesale disappearance must leave a trace
        schemaResolve: {
            via: schemaResolve.via || null,
            error: schemaResolve.error || null,
            tried: schemaResolve.tried,
        },
        recentRuns: runs.map((r) => formatRun(r)),
        ledger: s.ledger || null, // v0.8.10: on-disk ledger (still queryable after a backend restart)
        // v0.9.3: workDir writability self-proof (writing the ledger/logs on a read-only mount fails silently — this has to be said out loud)
        workDir: ledger ? ledger.workDir || null : null,
        workDirWritable: !!(ledger && ledger.writable),
        workDirWarning: ledger && !ledger.writable ? text(ledger.hint || ledger.lastError || '') : null,
    };
    return appendAddonVerdict(payload, s);
}
/** When the addon has a problem, mark it honestly; next_action points at the Blender addon (not op=start). */
function appendAddonVerdict(payload, s) {
    if (!s.addonError)
        return JSON.stringify(payload);
    const addonError = text(s.addonError);
    payload.addonError = addonError;
    const busy = BUSY_RE.test(addonError);
    const timeout = !busy && isTimeoutError(addonError);
    payload.code = busy ? 'busy_render' : timeout ? 'addon_unresponsive' : 'addon_error';
    payload.next_action = busy
        ? 'Blender is rendering (BUSY_RENDER): wait for the render to finish with blender_rt_plan(op="render_wait"), or wait until it is done before sending again; for long renders go through blender_rt_job from the start. Do not use op=start (that only fixes the 9877 backend process)'
        : timeout
            ? 'the backend (9877) is up but addon/bpy did not answer within the budget: check whether Blender is running and "DSH Blender Bridge" has been Connected, and whether it is stuck in a render/modal operation; after reloading the addon re-check with op=doctor'
            : 'the backend (9877) is up and the addon returned an error: fix it per addonError (check whether Blender is running and "DSH Blender Bridge" is Connected), then re-check with op=doctor';
    return JSON.stringify(payload);
}
function formatRun(raw) {
    const x = asRecord(raw);
    const expect = asRecord(x.expect);
    return {
        id: x.id,
        status: x.status,
        pid: x.pid,
        ms: x.ms,
        outdir: x.outdir,
        artifacts: x.artifactCount,
        expectOk: x.expect ? expect.ok : null,
    };
}
/** Timeout/aborted ≠ connection refused — the shared criterion behind the two verdicts. */
export function isTimeoutError(e) {
    const name = e && typeof e === 'object' ? String(e.name || '') : '';
    return name === 'TimeoutError' || name === 'AbortError' || TIMEOUT_RE.test(errorText(e));
}
export function formatStatusError(port, e) {
    const err = errorText(e);
    // Order: render busy → connection-level failure → host wait timeout → unclassified.
    // ETIMEDOUT / connect timeout are connection-level failures and belong to backend_unreachable; deciding timeout first here would misreport.
    if (BUSY_RE.test(err))
        return JSON.stringify({
            running: false,
            url: base(port) + '/',
            error: err,
            code: 'busy_render',
            next_action: 'Blender is rendering (BUSY_RENDER): wait for the render to finish with blender_rt_plan(op="render_wait"); for long renders switch to blender_rt_job; do not use op=start (the backend process does not need a restart)',
            hint: 'the main thread is occupied by the render, so the bpy round-trip for /status cannot get into the queue; check again once the render finishes',
        });
    const refused = CONN_RE.test(err);
    if (refused)
        return JSON.stringify({
            running: false,
            url: base(port) + '/',
            error: err,
            code: 'backend_unreachable',
            next_action: 'bring the backend up with blender_viewport op=start; if it still fails, see op=doctor',
            hint: 'connection-layer failure (refused / reset / connect timeout): nothing usable is listening on 9877 — bring the backend up with blender_viewport op=start',
        });
    if (isTimeoutError(e))
        return JSON.stringify({
            running: false,
            url: base(port) + '/',
            error: err,
            code: 'backend_timeout',
            next_action: 'first run blender_viewport op=doctor (bounded, ≤10s) to confirm whether addon/bpy is available; do not repeat op=start — a timeout does not mean the backend is down',
            hint: 'this time the /status receipt did not arrive within the budget: the addon/bpy round-trip may be stuck (Blender rendering/modal operation), or this wait was interrupted by the host; if /health answers, the backend process is up',
        });
    return JSON.stringify({
        running: false,
        url: base(port) + '/',
        error: err,
        code: 'backend_unreachable',
        next_action: 'use blender_viewport op=doctor to identify the cause first (check /health); if it really is not up, then op=start',
        hint: 'not classified as a connection-level failure: check /health with op=doctor first, then decide whether to op=start',
    });
}
/**
 * Put the cause into the error text (Node fetch hides ECONNREFUSED inside TypeError('fetch failed').cause).
 * Depth/cycle protection: a host or third-party error may chain cause into a cycle, and recursive string building would blow up the presenter itself.
 */
function errorText(e, depth = 0, seen = []) {
    if (e instanceof Error) {
        if (depth >= MAX_CAUSE_DEPTH)
            return e.message + ' … (cause chain too deep, truncated)';
        if (seen.indexOf(e) !== -1)
            return '[cyclic cause: ' + e.message + ']';
        const cause = e.cause;
        return cause === undefined
            ? e.message
            : e.message + ': ' + errorText(cause, depth + 1, seen.concat([e]));
    }
    return String(e);
}
//# sourceMappingURL=presenter.js.map