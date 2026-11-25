import { wslToWin } from '../../config.js';
import { isJobMode } from './job-mode.js';
import { buildRunReceipt, collectHeadlessOutcome, finishRunRecord, headlessJobReceipt, prepareRun, recordCompletedRun, } from './run-stages.js';
export function createHeadlessRun(E) {
    const { LEDGER, SESSION_NAME, dumpResult, jobStart, ledgerAppend, metrics, readScriptPath, runs, } = E;
    return {
        async headless(opts = {}) {
            const run = prepareRun(opts, E);
            // v0.8.7 (external feedback #4) / v0.9.3: long tasks move to the job layer — a client timeout no longer drops the result.
            // Usage: as_job=true forces it; or pass auto_job_ms (e.g. 120000) to route to a job when the estimate exceeds it.
            // The sync check sits before await: in non-job mode we must enter spawn synchronously, as before the split.
            if (isJobMode(opts, run.p)) {
                const job = await headlessJobReceipt({
                    opts,
                    p: run.p,
                    t0: run.t0,
                    logStreams: run.logStreams,
                    runs,
                    jobStart,
                });
                if (job)
                    return job;
            }
            const outcome = await collectHeadlessOutcome({
                p: run.p,
                built: run.built,
                opts,
                runRec: run.runRec,
                logStreams: run.logStreams,
                logDirWsl: run.logDirWsl,
                t0: run.t0,
                sessionName: SESSION_NAME,
                metrics,
                dumpResult,
                readScriptPath,
            });
            // ---- v0.8.10: ledger terminal state (the structured receipt's "truth" lands on runRec)
            recordCompletedRun({
                p: run.p,
                runRec: run.runRec,
                res: outcome.res,
                failureClass: outcome.failureClass,
                artifacts: outcome.artifacts,
                logs: outcome.logs,
                expectEval: outcome.expectEval,
                parsed: outcome.parsed,
                parsedOut: outcome.parsedOut,
                outJsonInfo: outcome.outJsonInfo,
                resultTruncated: outcome.resultTruncated,
                pathWarnings: outcome.pathWarnings,
                shotsSummary: outcome.shotsSummary,
                ledgerAppend,
            });
            finishRunRecord({
                runRec: run.runRec,
                stopRunHb: run.stopRunHb,
                pathWarnings: outcome.pathWarnings,
                stdout: outcome.stdout,
                stderr: outcome.stderr,
                fileOpt: run.p.fileOpt,
                fileLooksPython: run.p.fileLooksPython,
            });
            const receipt = buildRunReceipt({
                outcome,
                p: run.p,
                opts,
                runRec: run.runRec,
                sessionName: SESSION_NAME,
                ledgerWin: wslToWin(LEDGER),
            });
            await outcome.logsClosed;
            return receipt;
        },
    };
}
//# sourceMappingURL=index.js.map