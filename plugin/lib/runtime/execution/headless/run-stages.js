// Headless run stages: job hand-off, process result collection, ledger
// completion and receipt assembly. Extracted verbatim from createHeadlessRun().headless()
// with behavior frozen; index.ts only sequences these stages.
import { winToWsl } from '../../config.js';
import { PLUGIN_VERSION, pathAudit, sceneHygieneAudit } from '../../core/evidence.js';
import { BLENDER_EXE, WIN_TMP } from '../../paths.js';
import { buildChildEnv } from './child-env.js';
import { buildHeadlessScript } from './script.js';
import { createHeadlessLogStreams } from './process.js';
import { prepareHeadlessOptions } from './options/index.js';
import { createRunState } from './run-state.js';
import { closeHeadlessLogStreams, executeHeadless } from './execute.js';
import { isJobMode, jobModeReceipt } from './job-mode.js';
import { writeFallbackLogs } from './logs.js';
import { buildHeadlessReceipt } from './receipt.js';
import { applyShotsResult, classifyFailure, collectArtifacts, evaluateExpect, extractFailureContext, failureHint, gpuAfterEngine, parseHeadlessStdout, finishRunWarnings, summarizeShots, withWorkdirWarning, writeResultJson, } from './result.js';
/** Prepare options/script/log streams and register the running record (metrics + ledger). */
export function prepareRun(opts, deps) {
    const t0 = Date.now();
    const p = prepareHeadlessOptions(opts, deps);
    const built = buildHeadlessScript(p);
    deps.metrics.headlessRuns++;
    // ---- v0.9.3: logs are written **while the run proceeds** + run ledger registration (ids share the job space: op=status/collect id=run-…)
    const logDirWsl = p.outdirWsl || winToWsl(WIN_TMP);
    const logStreams = createHeadlessLogStreams(logDirWsl, t0, p.runId);
    const { runRec, stopRunHb } = createRunState({
        p,
        built,
        t0,
        logDirWsl,
        logs: logStreams.logs,
        runs: deps.runs,
        ledgerAppend: deps.ledgerAppend,
    });
    return { t0, p, built, logDirWsl, logStreams, runRec, stopRunHb };
}
/** Long-task hand-off: delete the fake running record and return the job receipt (null when synchronous). */
export async function headlessJobReceipt(input) {
    const { opts, p, t0, logStreams, runs, jobStart } = input;
    if (!isJobMode(opts, p))
        return null;
    runs.delete(p.runId); // after handing off to a job this run no longer exists, don't leave a fake running record
    try {
        const j = jobStart(Object.assign({}, opts, { timeoutMs: Math.max(p.timeoutMs, 3600000), runId: p.runId }));
        return jobModeReceipt({ opts, p, t0, job: j });
    }
    finally {
        await closeHeadlessLogStreams(logStreams);
    }
}
/** Spawn, parse, classify and collect artifacts — the synchronous body of the run. */
export async function collectHeadlessOutcome(input) {
    const { p, built, opts, runRec, logStreams, logDirWsl, t0, sessionName, metrics } = input;
    // ---- child process env: optionally pass through the user's Blender config (GPU preferences live there)
    const childEnv = buildChildEnv(p, opts, sessionName);
    const { res, stdout, stderr, ms, logsClosed } = await executeHeadless({
        p,
        built,
        childEnv,
        runRec,
        logStreams,
        t0,
    });
    metrics.lastHeadlessMs = ms;
    const parsedOut = parseHeadlessStdout(stdout);
    let parsed = parsedOut.parsed;
    // ---- v0.9.3: silent path-rewrite audit
    const pathWarnings = pathAudit(stdout, stderr);
    // ---- v0.9.6: workDir is not shared → the script lands elsewhere; this must show up in the receipt (never silently)
    withWorkdirWarning(pathWarnings, built.sp ? built.sp.staging : null);
    // ---- log fallback: the normal path writes as it runs inside push(); when the streams never came up, write the full dump here once
    let logs = logStreams.logs;
    if (!logStreams.soStream) {
        logs = writeFallbackLogs(logDirWsl, logStreams.stamp, p.runId, stdout, stderr);
    }
    runRec.logs = logs;
    const failure = extractFailureContext(stderr, p.script);
    const artifacts = collectArtifacts(p.outdirWsl, t0, opts.includeNoise);
    const gpuFailed = p.gpuManual && parsedOut.gpu && parsedOut.gpu.ok === false;
    const expectEval = evaluateExpect(p.exp, stdout);
    const runOk = !res.timedOut && res.exitCode === 0 && !gpuFailed && (!expectEval || expectEval.ok);
    const failureClass = classifyFailure(res, !!gpuFailed, failure.lastException);
    const FAIL_HINT = failureHint(failureClass);
    // ---- v0.9.3: shots line + framing self-diagnosis (subject covers <5% of frame → warning)
    const shotsSummary = parsedOut.shotsRes ? summarizeShots(parsedOut.shotsRes) : null;
    parsed = applyShotsResult(parsed, shotsSummary);
    const outJsonInfo = writeResultJson(parsed, opts, { dumpResult: input.dumpResult, readScriptPath: input.readScriptPath }, p.runId);
    // ---- v0.8.10: ledger terminal state
    // v0.9.3: the "ground truth" of the structured receipt lives on runRec — op=collect/status and the synchronous receipt share one copy of the data
    const resultTruncated = !!(parsed !== null && outJsonInfo.path && outJsonInfo.bytes > 4000);
    return {
        childEnv,
        res,
        stdout,
        stderr,
        ms,
        logsClosed,
        parsedOut,
        parsed,
        pathWarnings,
        logs,
        failure,
        artifacts,
        gpuFailed: !!gpuFailed,
        expectEval,
        runOk,
        failureClass,
        failureHint: FAIL_HINT,
        shotsSummary,
        outJsonInfo,
        resultTruncated,
        built: built,
    };
}
/** Write the terminal state on runRec and append the done ledger row (failures ignored). */
export function recordCompletedRun(input) {
    const { p, runRec, res, failureClass, artifacts, logs, expectEval, parsed, parsedOut } = input;
    const { outJsonInfo, resultTruncated, pathWarnings, shotsSummary, ledgerAppend } = input;
    try {
        runRec.status = res.timedOut ? 'killed' : res.exitCode === 0 ? 'done' : 'failed';
        runRec.failureClass = failureClass;
        runRec.exitCode = res.exitCode;
        runRec.signal = res.signal;
        runRec.timedOut = !!res.timedOut;
        runRec.finishedAt = Date.now();
        runRec.ms = Number(runRec.finishedAt) - runRec.startedAt;
        runRec.artifacts = artifacts.artifacts.slice(0, 20).map((a) => a.name);
        runRec.logs = logs;
        runRec.expect = expectEval;
        runRec.result = parsed;
        runRec.parseError = parsedOut.parseError;
        runRec.resultPath = outJsonInfo.path;
        runRec.resultPathWsl = outJsonInfo.wsl || null;
        runRec.resultBytes = outJsonInfo.bytes;
        runRec.resultTruncated = resultTruncated;
        runRec.pathWarnings = pathWarnings;
        runRec.shots = shotsSummary;
        runRec.inputFile = p.inputFileInfo;
        ledgerAppend({
            id: p.runId,
            kind: 'headless',
            status: runRec.status,
            exitCode: res.exitCode,
            ms: runRec.ms,
            outdir: runRec.outdir,
            script: runRec.script,
            pid: runRec.pid,
            file: p.fileOpt === undefined ? null : String(p.fileOpt),
            inputFile: p.inputFileInfo, // F-09
            stage: runRec.stageName || null,
            resultPath: outJsonInfo.path,
            stageMs: typeof runRec.stageAt === 'number' ? runRec.stageAt - runRec.startedAt : null,
            artifacts: runRec.artifacts.slice(0, 8),
            expectOk: expectEval ? expectEval.ok : null,
        });
    }
    catch (e) {
        /* ignore */
    }
}
/** Stop the heartbeat and merge path/hygiene/no-input warnings (same order as before). */
export function finishRunRecord(input) {
    const { runRec, stopRunHb, pathWarnings, stdout, stderr, fileOpt, fileLooksPython } = input;
    try {
        if (stopRunHb)
            stopRunHb();
    }
    catch (e) { }
    runRec.warnings = finishRunWarnings(pathWarnings, sceneHygieneAudit(stdout, stderr), fileOpt, fileLooksPython);
}
/** Assemble the public receipt from the collected outcome (same fields/order as before). */
export function buildRunReceipt(input) {
    const { outcome, p, opts, runRec, sessionName, ledgerWin } = input;
    return buildHeadlessReceipt({
        ok: outcome.runOk,
        runId: p.runId,
        session: sessionName,
        pluginVersion: PLUGIN_VERSION,
        expect: outcome.expectEval,
        runRec: runRec,
        stdout: outcome.stdout,
        stderr: outcome.stderr,
        status: outcome.failureClass,
        failureHint: outcome.failureHint,
        ledgerWin: ledgerWin,
        scriptFile: p.scriptFileInfo,
        inputFile: p.inputFileInfo,
        outJson: outcome.outJsonInfo,
        result: outcome.parsed,
        parseError: outcome.parsedOut.parseError,
        shots: outcome.shotsSummary,
        pathWarnings: outcome.pathWarnings,
        ms: outcome.ms,
        timeoutMs: p.timeoutMs,
        outdirWin: p.outdirWin,
        outdirWsl: p.outdirWsl,
        childEnvKeys: Object.keys(outcome.childEnv).filter((k) => k.indexOf('DSH_') === 0),
        res: outcome.res,
        logs: outcome.logs,
        failure: outcome.failure,
        artifacts: outcome.artifacts,
        noiseFiltered: outcome.artifacts.noiseFiltered,
        blenderExe: BLENDER_EXE,
        built: outcome.built,
        preload: p.mods.length ? p.mods : undefined,
        gpu: outcome.parsedOut.gpu,
        engine: gpuAfterEngine(outcome.parsedOut.gpu),
        engineMode: (outcome.parsedOut.gpu && outcome.parsedOut.gpu.mode) || null,
        useUserConfig: !!opts.useUserConfig,
        resultTruncated: outcome.resultTruncated,
    });
}
//# sourceMappingURL=run-stages.js.map