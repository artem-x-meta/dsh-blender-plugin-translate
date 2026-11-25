/** blender_rt_job execution layer: parameter validation → backend call → receipt assembly (behaviour identical to v2.6.2). */
import { ensureBackend } from '../../host/backend/index.js';
import { backendPost, leasedText, splitArgs } from '../../host/http.js';
import { detectFileAlias } from '../../host/runtime-bridge.js';
import { toolError } from '../errors.js';
import { asRecord, optionalText, text } from '../../contracts/dynamic.js';
import { buildCollectRunning, buildFinalJob, buildJobKill, buildJobStart, buildLedgerJob, buildRecoveredJob, buildWaitTimeout, renderJobList, } from './presenter.js';
export async function executeJob(args, port) {
    if (!(await ensureBackend(port)))
        return toolError('backend_unreachable', 'backend unavailable (127.0.0.1:' + String(port) + ')', 'bring the backend up first with blender_viewport op=start, then retry');
    const op = text(args.op) || 'list';
    // F-09 consistency: file= on op=start/run gets the same interception as rt_headless (the engine job path already has validateFileOpt as a backstop)
    const bad = validateFileArgs(op, args);
    if (bad)
        return bad;
    const r = await backendPost(port, '/job', buildJobBody(op, args), budgetFor(op, args));
    const lt = leasedText(r);
    if (lt)
        return { text: lt };
    if (!r || r.ok !== true) {
        const errText = text(r.error || r.raw || 'unknown');
        // a failure caused by an empty blenderExe must carry its own code, otherwise the model sees a generic backend_error
        // and gets no actionable guidance on how to configure blender.exe.
        if (text(r.code) === 'blender_exe_missing')
            return toolError('blender_exe_missing', 'JOB ' + op + ' failed · ' + errText, 'set DSH_BLENDER_EXE or blenderExe in dsh-blender.config.json (the Steam path looks like <Steam>\\steamapps\\common\\Blender\\blender.exe); restart DSH after the change, then retry blender_rt_job op=start');
        return toolError('backend_error', 'JOB ' + op + ' failed · ' + errText, 'use blender_rt_job op=list to inspect the jobs');
    }
    if (op === 'list')
        return renderJobList(r);
    return reportJob(op, asRecord(r.job));
}
function validateFileArgs(op, args) {
    if (op !== 'start' && op !== 'run')
        return null;
    const aliasKeys = detectFileAlias(args);
    if (aliasKeys.length)
        return toolError('invalid_params', 'blender_rt_job has no parameter ' +
            aliasKeys.join(', ') +
            '; to open a .blend use file=. (keys received: ' +
            Object.keys(args).join(', ') +
            ')', 'use file=<.blend path>; the parameter name is file, not blend/path');
    if (typeof args.file === 'string' && !args.file.trim())
        return toolError('invalid_params', 'file= was given an empty string — no .blend will be opened this time (the script receives the factory empty scene)', 'give a real .blend path, or do not pass file=');
    return null;
}
function buildJobBody(op, args) {
    const body = { op: op };
    if (args.id)
        body.id = text(args.id);
    if (args.script !== undefined)
        body.script = text(args.script);
    if (args.script_file)
        body.scriptFile = text(args.script_file);
    if (args.args)
        body.args = splitArgs(args.args);
    if (args.env && typeof args.env === 'object')
        body.env = args.env;
    if (args.file)
        body.file = text(args.file);
    if (args.outdir)
        body.outdir = text(args.outdir);
    if (args.engine)
        body.engine = text(args.engine);
    if (args.preload)
        body.preload = text(args.preload);
    if (args.workdir)
        body.workdir = text(args.workdir);
    if (args.out_json)
        body.outJson = text(args.out_json);
    if (args.include_noise !== undefined)
        body.includeNoise = !!args.include_noise;
    if (args.factory_startup !== undefined)
        body.factoryStartup = !!args.factory_startup;
    if (args.bootstrap !== undefined)
        body.bootstrap = !!args.bootstrap;
    if (args.tail)
        body.tail = Number(args.tail);
    if (args.timeout_ms)
        body.timeoutMs = Number(args.timeout_ms);
    return body;
}
// v0.9.3: op=wait blocks → give it a full HTTP budget (server default 120 s per call, cap 600 s)
function budgetFor(op, args) {
    return op === 'wait' ? Math.min(600000, Number(args.timeout_ms) || 120000) + 30000 : 60000;
}
function reportJob(op, j) {
    // ---- unified receipt: run/job share one set of fields
    const ctx = {
        mode: 'job',
        jobId: text(j.id).indexOf('job-') === 0 ? text(j.id) : null,
        runId: optionalText(j.runId) || null,
        notes: [],
        hint: null,
    };
    if (op === 'start')
        return buildJobStart(j, ctx);
    if (op === 'kill')
        return buildJobKill(j);
    if (j.recovered)
        return buildRecoveredJob(j, op);
    if (j.status === 'stale' || j.fromLedger)
        return buildLedgerJob(j, op);
    if (op === 'collect' && j.status === 'running')
        return buildCollectRunning(j, ctx);
    if (op === 'wait' && j.waitTimedOut)
        return buildWaitTimeout(j);
    const notes = [];
    if (op === 'wait')
        notes.push('op=wait waited for the terminal state (waited ' + String(Math.round(Number(j.waitedMs || 0) / 1000)) + 's)');
    if (j.kind === 'headless' || text(j.id).indexOf('run-') === 0)
        notes.push('this is the blender_rt_headless run ledger (run and job share one id space)');
    return buildFinalJob(j, ctx, notes);
}
//# sourceMappingURL=execute.js.map