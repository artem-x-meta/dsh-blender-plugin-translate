// plan/qc/audit prefix routing (split out of dispatch.ts; table-driven from config/routing.json)
import { WIN_TMP, blenderJoin } from '../../paths.js';
import { extractLoop } from '../output/index.js';
import { KERNEL_BOOTSTRAP } from '../kernel/index.js';
import { MAIN_ROUTES, MODULE_ROUTES } from './routes.generated.js';
export const hit = (result) => ({
    matched: true,
    result: Promise.resolve(result),
});
export const miss = () => ({ matched: false });
/** evidence: inject the default view.path first, then go through the contract layer */
export async function prepareEvidencePayload(E, o, payload) {
    if (o !== 'evidence')
        return payload;
    await E.ensureView();
    const { SESSION_NAME } = E;
    const p = payload !== null && typeof payload === 'object' ? payload : {};
    const viewRec = p.view !== null && typeof p.view === 'object' ? p.view : {};
    if (!viewRec.path)
        viewRec.path = blenderJoin(WIN_TMP, 'dsh_evidence_' + SESSION_NAME.replace(/[^A-Za-z0-9_.-]/g, '_') + '.png');
    p.view = viewRec;
    return p;
}
/** Generic: hand op to the Blender-side kernel module's dispatch(op, json) */
export async function dispatchViaKernelModule(E, ensure, api, subOp, payload, timeoutMs) {
    await ensure();
    const body = 'print("LOOP " + K.' +
        api +
        '["dispatch"](' +
        JSON.stringify(subOp) +
        ', _json.dumps(_json.loads(' +
        JSON.stringify(JSON.stringify(payload || {})) +
        '))))';
    return extractLoop(await E.addon.send('execute_code', { code: KERNEL_BOOTSTRAP + '\nimport json as _json\n' + body }, timeoutMs));
}
/** Match/slice rule shared by the generated tables: exact rows require op equality, prefix rows match by prefix. */
export function routeMatches(route, o) {
    return route.match === 'exact' ? o === route.op : o.indexOf(route.prefix) === 0;
}
/** A fixed sub (alias) wins; otherwise strip the prefix from op using the strip length in the table. */
function routeSubOp(route, o) {
    return route.sub === null ? o.slice(route.strip) : route.sub;
}
async function handleQcRender(E, route, o, payload) {
    const p = payload !== null && typeof payload === 'object' ? payload : {};
    if (p.asJob) {
        const { preloadChunk, jobStart } = E;
        const mods = String(route.preload || 'qc,qc_render')
            .split(',')
            .map(preloadChunk)
            .join(String.fromCharCode(10));
        const driver = 'import json as _json' +
            String.fromCharCode(10) +
            'print("HEADLESS " + K.' +
            route.api +
            '["render_views"](_json.loads(' +
            JSON.stringify(JSON.stringify(p)) +
            ')))';
        const j = jobStart({
            file: p.file,
            outdir: p.outdir || WIN_TMP,
            engine: p.engine && String(p.engine) !== 'keep' ? String(p.engine) : 'eevee',
            timeoutMs: Number(p.timeoutMs) || 3600000,
            script: mods + String.fromCharCode(10) + driver,
        });
        return {
            ok: true,
            mode: 'job',
            jobId: j.id,
            ms: 0,
            outdir: j.outdir,
            logDir: j.logDir,
            jsonl: blenderJoin(String(p.outdir || WIN_TMP), 'render_views.jsonl'),
            job: j,
            hint: 'long-running work moved to the job layer: follow up with blender_rt_job(op="status"/"collect", id="' +
                j.id +
                '"); artifacts and logs live under outdir/jobs/',
        };
    }
    return dispatchViaKernelModule(E, E[route.ensure], route.api, routeSubOp(route, o), p, route.timeoutMs);
}
async function handleMontage(E, route, payload) {
    await E[route.ensure]();
    const body = 'print("LOOP " + K.' +
        route.api +
        '["montage"](_json.loads(' +
        JSON.stringify(JSON.stringify(payload || {})) +
        ')))';
    return extractLoop(await E.addon.send('execute_code', { code: KERNEL_BOOTSTRAP + '\nimport json as _json\n' + body }, route.timeoutMs));
}
/** the motion_/deliver_ module API is not a uniform dispatch, so call by function name directly (behaviour frozen). */
async function handleModuleAlias(E, route, o, payload) {
    await E[route.ensure]();
    const name = o.slice(route.strip);
    const body = [
        'import json as _json',
        'A = K.' + route.api,
        'P = _json.loads(' + JSON.stringify(JSON.stringify(payload || {})) + ')',
        'if isinstance(P, dict) and isinstance(P.get("args"), dict): P = P["args"]',
        'print("LOOP " + (A["dispatch"](' +
            JSON.stringify(name) +
            ', _json.dumps(P)) if A.get("dispatch") else A[' +
            JSON.stringify(name) +
            '](**P)))',
    ].join(String.fromCharCode(10));
    return extractLoop(await E.addon.send('execute_code', { code: KERNEL_BOOTSTRAP + '\n' + body }, route.timeoutMs));
}
/** gui_* uses dsh_view_api's direct-call entry (the name always carries the gui_ prefix). */
async function handleView(E, route, o, payload) {
    await E[route.ensure]();
    const name = 'gui_' + o.slice(route.strip);
    const body = 'print("LOOP " + K.' +
        route.api +
        '[' +
        JSON.stringify(name) +
        '](**_json.loads(' +
        JSON.stringify(JSON.stringify(payload || {})) +
        ')))';
    return extractLoop(await E.addon.send('execute_code', { code: KERNEL_BOOTSTRAP + '\nimport json as _json\n' + body }, route.timeoutMs));
}
/** render_* lock-query aliases (render_lock_status -> status) are declared explicitly in routing.json. */
async function handleRender(E, route, o, payload) {
    await E[route.ensure]();
    const rest = o.slice(route.strip);
    const sub = route.subAliases[rest] || rest;
    const body = 'print("LOOP " + K.' +
        route.api +
        '["dispatch"](' +
        JSON.stringify(sub) +
        ', _json.dumps(_json.loads(' +
        JSON.stringify(JSON.stringify(payload || {})) +
        '))))';
    return extractLoop(await E.addon.send('execute_code', { code: KERNEL_BOOTSTRAP + '\nimport json as _json\n' + body }, route.timeoutMs));
}
/** Pick the call shape by the generated row's kind; api/strip/sub/preload/timeout always come from config/routing.json. */
export async function handleRoute(E, route, o, payload) {
    switch (route.kind) {
        case 'qc-render':
            return handleQcRender(E, route, o, payload);
        case 'montage':
            return handleMontage(E, route, payload);
        case 'motion':
        case 'deliver':
            return handleModuleAlias(E, route, o, payload);
        case 'view':
            return handleView(E, route, o, payload);
        case 'render':
            return handleRender(E, route, o, payload);
        default:
            return dispatchViaKernelModule(E, E[route.ensure], route.api, routeSubOp(route, o), payload, route.timeoutMs);
    }
}
async function routeTable(E, o, payload, routes) {
    for (const route of routes) {
        if (!routeMatches(route, o))
            continue;
        return hit(handleRoute(E, route, o, payload));
    }
    return miss();
}
export async function routeMainPlanOps(E, o, payload) {
    return routeTable(E, o, payload, MAIN_ROUTES);
}
export async function routeModulePlanOps(E, o, payload) {
    return routeTable(E, o, payload, MODULE_ROUTES);
}
//# sourceMappingURL=plan-call.js.map