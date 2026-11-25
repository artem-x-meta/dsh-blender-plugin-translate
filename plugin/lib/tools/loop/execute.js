/** loop execution layer: the GUI timers channel and the headless worker session channel. */
import { BACKEND_HINT } from '../../constants.js';
import { ensureBackend } from '../../host/backend/index.js';
import { backendPost, leasedText } from '../../host/http.js';
import { asRecord, text } from '../../contracts/dynamic.js';
import { redactSecrets, toolError } from '../errors.js';
import { loopResultText, loopSessionError, loopSessionText } from './response.js';
export async function executeLoop(port, args) {
    if (!(await ensureBackend(port)))
        return toolError('backend_unreachable', 'backend unavailable (127.0.0.1:' + String(port) + ')', BACKEND_HINT);
    const op = text(args.op) || 'status';
    const target = text(args.target) || 'gui';
    if (target === 'session')
        return loopViaSession(port, args, op);
    return loopGui(port, args, op);
}
async function loopViaSession(port, args, op) {
    const nm = text(args.session) || 'dsh-loop';
    const st = await backendPost(port, '/worker', { op: 'start', name: nm, preload: 'runner', engine: 'workbench', warmup: true, isolated: true }, 120000);
    if (!st || st.ok !== true)
        return toolError('backend_error', 'LOOP session start failed · ' + text(st.error || st.raw || 'unknown'), 'First start a worker with blender_rt_worker op=start, or switch to the GUI channel');
    const code = buildSessionCode(op, args);
    const r = await backendPost(port, '/worker', { op: 'exec', name: nm, code: code, isolated: true }, 300000);
    const rr = asRecord(r.result);
    if (!r || r.ok !== true)
        return toolError('backend_error', loopSessionError(op, nm, redactSecrets(text(r.error || rr.error || 'unknown'))), 'Use blender_rt_loop op=status to inspect the session; re-run op=start if needed');
    return { text: loopSessionText(op, nm, rr.result || rr || r) };
}
/** Builds the Python snippet the session channel runs for a given op (inner JSON double-encoded, byte-identical to the old implementation). */
function buildSessionCode(op, args) {
    const specJ = JSON.stringify(JSON.stringify(args.spec || {}));
    const nl = String.fromCharCode(10);
    return op === 'start'
        ? 'import json as _json' +
            nl +
            '_s = _json.loads(' +
            specJ +
            ')' +
            nl +
            '_r = K.dsh_loop_api["sync"](_s)' +
            nl +
            'print("HEADLESS " + (_r if isinstance(_r, str) else _json.dumps(_r, ensure_ascii=False)))'
        : op === 'status'
            ? 'print("HEADLESS " + K.dsh_loop_api["status"](' +
                String(Number(args.history || 8)) +
                ', ' +
                String(Number(args.board || 0)) +
                '))'
            : op === 'board'
                ? 'print("HEADLESS " + K.dsh_loop_api["board"](' +
                    String(Number(args.limit || 10)) +
                    ', ' +
                    (args.groups === false ? 'False' : 'True') +
                    '))'
                : op === 'export'
                    ? 'print("HEADLESS " + K.dsh_loop_api["export"](' +
                        JSON.stringify(args.path ? text(args.path) : null) +
                        ', ' +
                        String(Number(args.top || 1)) +
                        ', ' +
                        (args.include_variants ? 'True' : 'False') +
                        ', ' +
                        JSON.stringify(text(args.note)) +
                        '))'
                    : op === 'stop'
                        ? 'print("HEADLESS " + K.dsh_loop_api["stop"]())'
                        : op === 'bench'
                            ? 'print("HEADLESS " + K.dsh_loop_api["bench"](' +
                                String(Number(args.iterations || 5000)) +
                                '))'
                            : 'print("HEADLESS " + K.dsh_loop_api["help"]())';
}
async function loopGui(port, args, op) {
    const payload = {
        op: op,
        spec: args.spec || {},
        history: args.history || 8,
        board: args.board || 0,
        limit: args.limit || 10,
        groups: !(args.groups === false),
        path: args.path,
        top: args.top || 1,
        include_variants: !!args.include_variants,
        note: args.note || '',
        iterations: args.iterations || 5000,
    };
    const r = await backendPost(port, '/loop', payload, 300000);
    const lt = leasedText(r);
    if (lt)
        return { text: lt };
    if (!r || r.ok !== true)
        return toolError('backend_error', 'LOOP ' + op + ' failed · ' + text(r.error || r.raw || 'unknown'), 'Use blender_rt_loop op=status to inspect the session');
    return { text: loopResultText(op, r.result) };
}
//# sourceMappingURL=execute.js.map