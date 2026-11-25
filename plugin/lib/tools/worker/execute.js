import { BACKEND_HINT } from '../../constants.js';
import { ensureBackend } from '../../host/backend/index.js';
import { backendPost, leasedText, numTriple } from '../../host/http.js';
import { toAttachment, readLocalPng } from '../../utils/image.js';
import { redactSecrets, toolError } from '../errors.js';
import { asArray, asRecord, text } from '../../contracts/dynamic.js';
const LF = String.fromCharCode(10);
export async function executeWorker(args, ctx, port) {
    if (!(await ensureBackend(port)))
        return toolError('backend_unreachable', 'backend unavailable (127.0.0.1:' + String(port) + ')', BACKEND_HINT);
    const op = text(args.op) || 'status';
    const body = buildWorkerBody(op, args);
    const budget = 60000 + Number(body.timeoutMs || 120000);
    const r = await backendPost(port, '/worker', body, budget);
    const lt = leasedText(r);
    if (lt)
        return { text: lt };
    if (!r || r.ok !== true)
        return workerFailure(op, r);
    const res = asRecord(r.result);
    if (op === 'see')
        return workerSee(ctx, res);
    if (op === 'reset')
        return workerReset(res);
    if (op === 'exec')
        return workerExec(res);
    if (op === 'list')
        return workerList(res);
    return workerStatus(op, res);
}
function buildWorkerBody(op, args) {
    const body = { op: op, isolated: true };
    if (args.code !== undefined)
        body.code = text(args.code);
    if (args.timeout_ms)
        body.timeoutMs = Number(args.timeout_ms);
    if (args.gpu)
        body.gpu = text(args.gpu);
    if (args.engine)
        body.engine = text(args.engine);
    if (args.preload)
        body.preload = text(args.preload);
    if (args.warmup !== undefined)
        body.warmup = !!args.warmup;
    if (args.purge_prefix)
        body.purgePrefix = text(args.purge_prefix);
    if (args.name)
        body.name = text(args.name);
    if (op === 'see') {
        const vs = text(args.view_size) || '560x315';
        const mm = vs.match(/^(\d+)\s*[x×]\s*(\d+)$/);
        body.spec = {
            from: numTriple(args.from) || [7, -7, 5],
            look_at: numTriple(args.look_at) || [0, 0, 1],
            lens: args.lens !== undefined ? Number(args.lens) : undefined,
            ortho: args.ortho !== undefined ? !!args.ortho : undefined,
            ortho_scale: args.ortho_scale !== undefined ? Number(args.ortho_scale) : undefined,
            shading: args.shading || undefined,
            width: mm ? Number(mm[1]) : 560,
            height: mm ? Number(mm[2]) : 315,
        };
    }
    return body;
}
function workerFailure(op, raw) {
    const r = asRecord(raw);
    const rr = asRecord(r.result);
    const bits = [];
    bits.push('WORKER ' + op + ' failed · ' + text(r.error || rr.error || 'unknown'));
    if (rr.traceback)
        bits.push('--- traceback ---' + LF + redactSecrets(rr.traceback).slice(0, 2000));
    if (rr.stderr && String(rr.stderr).trim())
        bits.push('stderr: ' + redactSecrets(rr.stderr).slice(0, 1200));
    if (rr.stdout && String(rr.stdout).trim())
        bits.push('stdout: ' + redactSecrets(rr.stdout).slice(0, 800));
    if (r.hint)
        bits.push(text(r.hint));
    if (text(r.code) === 'blender_exe_missing')
        return toolError('blender_exe_missing', bits.join(LF), 'set DSH_BLENDER_EXE or blenderExe in dsh-blender.config.json (the Steam path looks like <Steam>\\steamapps\\common\\Blender\\blender.exe); after the change restart DSH, then retry blender_rt_worker op=start');
    return toolError('backend_error', bits.join(LF), 'check the backend /worker route; run blender_viewport op=doctor first to look at the process and port');
}
async function workerSee(ctx, res) {
    if (res.ok === false)
        return toolError('backend_error', 'WORKER see failed · ' + text(res.error || 'unknown'), 'use blender_rt_worker op=start to check the headless worker; or switch to blender_rt_see', res.traceback ? redactSecrets(res.traceback).slice(-1200) : undefined);
    let data = null;
    if (res.png_b64) {
        try {
            data = Buffer.from(text(res.png_b64), 'base64');
        }
        catch {
            data = null;
        }
    }
    if (!data && res.path)
        data = readLocalPng(res.path);
    const att = data
        ? await toAttachment(ctx, data, 'worker-see-' + String(Date.now()) + '.png')
        : { why: 'no png_b64/path' };
    const textOut = formatWorkerSeeText(res);
    return att.ref
        ? { text: textOut, image: att.ref }
        : { text: textOut + LF + '⚠ image not returned: ' + text(att.why || 'unknown reason') };
}
function formatWorkerSeeText(res) {
    return ('WORKER see ok · ' +
        text(res.ms) +
        'ms · ' +
        text(res.width) +
        'x' +
        text(res.height) +
        ' · ' +
        text(res.bytes || 0) +
        'B · ' +
        text(res.mode || 'workbench') +
        (res.coverage_estimate === null || res.coverage_estimate === undefined
            ? ''
            : ' · coverage ' + (Number(res.coverage_estimate) * 100).toFixed(2) + '%'));
}
function workerReset(res) {
    if (!res.ok)
        return toolError('backend_error', 'WORKER reset failed · ' + text(res.error || 'unknown'), 'use blender_rt_worker op=list to inspect the sessions; re-run op=start if needed');
    return { text: 'WORKER reset ok · objects=' + text(res.objects) };
}
function workerExec(res) {
    if (!res.ok)
        return toolError('backend_error', 'WORKER exec failed · ' + text(res.error || 'unknown'), 'use blender_rt_worker op=start to check the session; or switch to blender_rt_headless', res.traceback ? redactSecrets(res.traceback).slice(0, 1500) : undefined);
    const parts = [];
    parts.push('WORKER exec ok · ' + text(res.ms) + 'ms');
    if (res.result)
        parts.push('result: ' + JSON.stringify(res.result).slice(0, 2000));
    if (res.stdout && String(res.stdout).trim())
        parts.push('--- stdout ---' + LF + redactSecrets(res.stdout).slice(-2500));
    if (res.stderr && String(res.stderr).trim())
        parts.push('--- stderr ---' + LF + redactSecrets(res.stderr).slice(-1200));
    return { text: parts.join(LF) };
}
function workerList(res) {
    const ws = asArray(res.workers);
    const lines = ws.length
        ? ws.map((raw) => {
            const w = asRecord(raw);
            return ('- ' +
                text(w.name) +
                (w.alive
                    ? w.ready
                        ? ' · hot (pid ' +
                            text(w.pid) +
                            ', port ' +
                            text(w.port) +
                            ', up ' +
                            String(Math.round(Number(w.uptimeMs || 0) / 1000)) +
                            's)'
                        : ' · the process is there but not ready'
                    : ' · not started (port ' + text(w.port) + ')'));
        })
        : ['- (no worker instances yet; op=start starts one)'];
    return {
        text: 'WORKER list ok · ' + String(ws.length) + ' instances' + LF + lines.join(LF),
    };
}
function workerStatus(op, res) {
    const gpu = asRecord(res.gpu);
    const after = asRecord(gpu.after);
    const gpuEnabled = asArray(after.gpu_enabled);
    const parts = [];
    parts.push('WORKER ' +
        op +
        ' ok · ' +
        JSON.stringify({
            name: res.name,
            alive: res.alive,
            ready: res.ready,
            pid: res.pid,
            port: res.port,
            uptimeMs: res.uptimeMs,
        }));
    if (res.gpu)
        parts.push('GPU: ' +
            (gpu.fell_back_to_cpu ? '⚠️ fell back to CPU' : '✅ ' + text(after.device_type)) +
            ' ' +
            gpuEnabled.map(text).join(','));
    if (res.status)
        parts.push('status: ' + JSON.stringify(res.status));
    if (res.lastError)
        parts.push('lastError: ' + text(res.lastError));
    if (res.stdoutTail)
        parts.push('worker stdout tail: ' + redactSecrets(res.stdoutTail).slice(-800));
    return { text: parts.join(LF) };
}
//# sourceMappingURL=execute.js.map
