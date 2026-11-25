/** blender_viewport execution layer: op dispatch + one stage function per op (behaviour identical to v2.6.2). */
import { HOLDER, SERVER_PATH, VIEWPORT_DOCTOR_HEALTH_TIMEOUT_MS, VIEWPORT_START_STATUS_TIMEOUT_MS, } from '../../constants.js';
import { base, killBackendByCmd, killChildHandle, setPaused, sleep, startBackend, } from '../../host/backend/index.js';
import { backendJson, backendPost } from '../../host/http.js';
import { probeHttp, waitHttp } from '../../host/runtime-bridge.js';
import { errorMessage, text } from '../../contracts/dynamic.js';
import { formatDoctor, formatLaunch, formatLeaseError, formatLeaseResult, formatStatus, formatStatusError, formatWho, } from './presenter.js';
export async function executeViewport(args, port) {
    const op = text(args.op) || 'status';
    if (op === 'start')
        return opStart(port);
    if (op === 'restart')
        return opRestart(port);
    if (op === 'stop')
        return opStop(port);
    if (op === 'who' || op === 'lease' || op === 'release')
        return opLease(op, args, port);
    if (op === 'launch')
        return opLaunch(args, port);
    if (op === 'doctor')
        return opDoctor(port);
    return opStatus(port);
}
async function opStart(port) {
    setPaused(false);
    const url = base(port) + '/health';
    if (await probeHttp(url, 800))
        return formatBackendUp(port);
    const how = await startBackend(port);
    // Waiting is now "poll until it can really serve" (15 s), no longer "sleep a fixed window then probe once".
    if (await waitHttp(url, 15000, 300))
        return formatBackendUp(port, how);
    return ('start failed: ' +
        how +
        ' (still no /health within 15 s; try op=restart to clear leftover processes first, or check ' +
        SERVER_PATH +
        ' and node)');
}
/**
 * /health being reachable only proves the 9877 backend is alive, **it does not prove** Blender/addon/bpy is usable.
 * A bounded /status then checks the bpy round trip, separating "backend up + addon/bpy usable" from "backend up, addon not responding".
 */
async function formatBackendUp(port, how) {
    const endpoint = base(port) + '/';
    const addonDown = (detail) => 'backend up (9877) ' +
        endpoint +
        ': addon/bpy not responding: ' +
        detail +
        ' → check that Blender is running and "DSH Blender Bridge" is Connected (op=start only manages the backend process, it does not fix this channel; op=doctor re-checks)';
    let status;
    try {
        status = await backendJson(port, '/status', VIEWPORT_START_STATUS_TIMEOUT_MS);
    }
    catch (e) {
        return addonDown(errorMessage(e));
    }
    if (status.addonError)
        return addonDown(text(status.addonError));
    return ((how ? 'backend started (' + how + ')' : 'backend already running') +
        ': ' +
        endpoint +
        ' (watchdog enabled) · addon/bpy usable (/status bpy round trip OK)');
}
async function opRestart(port) {
    setPaused(false);
    killChildHandle();
    killBackendByCmd(port);
    await sleep(500);
    const how = await startBackend(port);
    if (await waitHttp(base(port) + '/health', 15000, 300))
        return 'backend restarted (' + how + '): ' + base(port) + '/';
    return 'restart failed: ' + how + ' (still no /health within 15 s)';
}
async function opStop(port) {
    setPaused(true);
    const notes = [];
    if (killChildHandle())
        notes.push('child handle killed');
    const killed = killBackendByCmd(port);
    if (killed.length)
        notes.push('leftover backend killed pid=' + killed.join(','));
    if (!notes.length)
        return 'no backend running (127.0.0.1:' + String(port) + '); watchdog paused';
    await sleep(400);
    return 'backend stopped: ' + notes.join(' · ') + ' (watchdog paused, op=start resumes)';
}
async function opLease(op, args, port) {
    try {
        if (op === 'who')
            return formatWho(await backendJson(port, '/who', 15000));
        const body = { holder: text(args.holder) || HOLDER };
        if (args.ttl_ms)
            body.ttlMs = Number(args.ttl_ms);
        if (op === 'lease' && args.force)
            body.force = true;
        if (op === 'lease' && args.scope)
            body.scope = text(args.scope);
        const r = await backendPost(port, op === 'lease' ? '/lease' : '/release', body, 20000);
        if (op === 'lease' && r.error === 'leased')
            return formatLeaseResult(op, r);
        return (op === 'lease' ? 'LEASE ' : 'RELEASE ') + JSON.stringify(r);
    }
    catch (e) {
        return formatLeaseError(op, e);
    }
}
async function opLaunch(args, port) {
    try {
        const body = {};
        if (args.wait_ms)
            body.waitMs = Number(args.wait_ms);
        if (args.file)
            body.file = text(args.file);
        if (args.exe)
            body.exe = text(args.exe);
        if (args.addon_module)
            body.addonModule = text(args.addon_module);
        if (args.addon_file)
            body.addonFile = text(args.addon_file);
        if (args.dry_run)
            body.dryRun = true;
        const r = await backendPost(port, '/launch', body, Math.max(30000, Number(args.wait_ms || 90000) + 30000));
        return formatLaunch(r);
    }
    catch (e) {
        return ('launch failed: ' +
            errorMessage(e) +
            ' (backend not up? run blender_viewport op=start first — that manages the **backend** process, this op is the one that manages Blender)');
    }
}
async function opDoctor(port) {
    try {
        return formatDoctor(await backendJson(port, '/doctor'));
    }
    catch (e) {
        const err = errorMessage(e);
        // Only when /health is also unreachable may we say "backend not up"; if the backend is up, it is an addon/bpy round-trip problem.
        const backendUp = await probeHttp(base(port) + '/health', VIEWPORT_DOCTOR_HEALTH_TIMEOUT_MS);
        if (backendUp)
            return ('health check failed: ' +
                err +
                ' (backend up (9877), doctor timed out/failed: the problem is in the addon or the bpy round trip — ' +
                'check that Blender is running and "DSH Blender Bridge" is Connected; op=start only manages the backend process and does not fix this channel; retry op=doctor later)');
        return 'health check failed: ' + err + ' (backend not up: blender_viewport op=start)';
    }
}
async function opStatus(port) {
    try {
        return formatStatus(port, await backendJson(port, '/status'));
    }
    catch (e) {
        return formatStatusError(port, e);
    }
}
//# sourceMappingURL=execute.js.map