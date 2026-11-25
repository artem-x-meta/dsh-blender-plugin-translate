import { ensureBackend } from '../../host/backend/index.js';
import { backendPost, leasedText, splitArgs } from '../../host/http.js';
import { HEADLESS_WAIT_MS, newRunId, promotedFromTimeout } from '../../headless/receipts/index.js';
import { detectFileAlias } from '../../host/runtime-bridge.js';
import { toolError } from '../errors.js';
import { asRecord, text } from '../../contracts/dynamic.js';
import { attachShots, missingResultText, runAsJob, syncReceipt } from './receipt.js';
export async function executeHeadless(args, ctx, port) {
    if (!(await ensureBackend(port)))
        return toolError('backend_unreachable', 'backend unavailable (127.0.0.1:' + String(port) + ')', 'the headless channel is managed by the backend process; run blender_viewport op=start first');
    const bad = validateFileArgs(args);
    if (bad)
        return bad;
    const runId = newRunId();
    const asJob = !!(args && args.as_job);
    const waitS = args && args.wait_s !== undefined && args.wait_s !== null && args.wait_s !== ''
        ? Number(args.wait_s)
        : null;
    const body = buildHeadlessBody(args, runId);
    const serverBudget = 60000 + Number(body.timeoutMs || 180000);
    const autoJobMs = Number(process.env.DSH_HEADLESS_AUTO_JOB_MS) || 0;
    // ---- v0.9.3: route decision
    //   as_job=true                → go to the background immediately (optional wait_s waits a bit longer)
    //   serverBudget >= autoJobMs  → same as above (when DSH_HEADLESS_AUTO_JOB_MS is explicitly set)
    //   otherwise                  → wait synchronously first, and when the window expires return a promoted receipt (the result is never lost)
    const wantJobFirst = asJob || (autoJobMs > 0 && serverBudget >= autoJobMs);
    if (wantJobFirst)
        return runAsJob(port, body, waitS, asJob, serverBudget, autoJobMs);
    return runSync(ctx, args, port, body, runId, serverBudget);
}
function validateFileArgs(args) {
    // F-09: the tool side must reject ALIAS / an empty string itself —— the old form stripped falsy values to undefined
    // while assembling the body, so the engine-side guard never fired on the tool path.
    const aliasKeys = detectFileAlias(args);
    if (aliasKeys.length)
        return toolError('invalid_params', 'blender_rt_headless has no argument ' +
            aliasKeys.join(', ') +
            '; to open a .blend use file=. (keys received: ' +
            Object.keys(args || {}).join(', ') +
            ')', 'use file=<.blend path> to open the scene; the argument name is file, not blend/path');
    const rawFile = args ? args.file : undefined;
    if (typeof rawFile === 'string' && !rawFile.trim())
        return toolError('invalid_params', 'file= was given an empty string — no .blend will be opened this run (the script gets the factory empty scene)', 'give a real .blend path, or do not pass file=');
    return null;
}
function buildHeadlessBody(args, runId) {
    const rawFile = args ? args.file : undefined;
    const body = {
        script: String(args.script || ''),
        file: rawFile === undefined || rawFile === null ? undefined : rawFile,
        outdir: args.outdir || undefined,
        timeoutMs: args.timeout_ms ? Number(args.timeout_ms) : undefined,
        factoryStartup: args.factory_startup !== false,
        bootstrap: args.bootstrap !== false,
        preload: args.preload || undefined,
        gpu: args.gpu || undefined,
        engine: args.engine || undefined,
        useUserConfig: !!args.use_user_config,
        includeNoise: !!args.include_noise,
        expect: args.expect && typeof args.expect === 'object' ? args.expect : undefined,
        workdir: args.workdir || undefined,
        scriptFile: args.script_file || undefined,
        env: args.env && typeof args.env === 'object' ? args.env : undefined,
        outJson: args.out_json || undefined,
        shots: args.shots || undefined,
        hardExit: args && typeof args.hard_exit === 'boolean' ? args.hard_exit : undefined,
        runId: runId, // v0.9.3: generated client-side → a usable handle is available the moment the window expires
    };
    if (args.args)
        body.args = splitArgs(args.args);
    return body;
}
async function runSync(ctx, args, port, body, runId, serverBudget) {
    let res;
    try {
        // budget = the wait window + a 2 s margin: on expiry it turns into a promoted receipt
        res = await backendPost(port, '/headless', body, Math.min(serverBudget, HEADLESS_WAIT_MS + 2000));
    }
    catch (e) {
        // v0.9.3: client window expired / host exec.signal cancelled —— the server-side child process is still running
        return await promotedFromTimeout(port, runId, e);
    }
    const lt = leasedText(res);
    if (lt)
        return { text: lt };
    if (!res || res.error) {
        const errText = String((res && (res.error || res.raw)) || 'unknown') +
            (res && res.hint ? '\n' + String(res.hint) : '');
        const code = res ? text(res.code) : '';
        // since v3.0.6 runtime /headless returns code=blender_exe_missing; the tool layer used to swallow it into backend_error,
        // which made the documented "headless reports blender_exe_missing" false.
        if (code === 'blender_exe_missing' || code === 'blender-exe-missing')
            return toolError('blender_exe_missing', 'HEADLESS failed · ' + errText, 'set DSH_BLENDER_EXE or blenderExe in dsh-blender.config.json (a Steam build looks like D:/.../steamapps/common/Blender/blender.exe); after changing it restart DSH, then retry blender_rt_headless');
        return toolError('backend_error', 'HEADLESS failed · ' + errText, 'check the Blender path/DSH backend; for details see blender_viewport op=doctor and the headless log');
    }
    // the backend /headless envelope is {ok, ms, result:<engine receipt>} —— the structured fields are inside result
    const bodyRes = res && res.result && typeof res.result === 'object' ? asRecord(res.result) : null;
    // note: "resultJson is empty" must **not** be taken as a missing field —— when the last line of the script is not JSON, resultJson is supposed to be null.
    if (!bodyRes ||
        (!bodyRes.status &&
            bodyRes.result === undefined &&
            bodyRes.resultJson === undefined &&
            !bodyRes.shots))
        return missingResultText(res, body);
    const out = syncReceipt(bodyRes, res);
    if (args && args.attach_images)
        out.images = await attachShots(ctx, out, args);
    return out;
}
//# sourceMappingURL=execute.js.map
