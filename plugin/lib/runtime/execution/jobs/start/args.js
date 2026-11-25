// job record / artifacts / persistence (split out of jobs/start.ts, behavior frozen)
import path from 'node:path';
import fs from 'node:fs';
import { winToWsl } from '../../../config.js';
import { PLUGIN_VERSION, pathAudit, sceneHygieneAudit } from '../../../core/evidence.js';
import { noInputFileWarning } from '../../../file_guard.js';
import { workdirStagingWarning } from '../../../proc_env.js';
import { errorMessage } from '../../../core/json.js';
import { jobArtifacts } from '../snapshot.js';
export function buildJobRecord(p) {
    const j = {
        kind: 'job',
        id: p.id,
        runId: p.runId,
        child: null,
        pid: null,
        startedAt: Date.now(),
        status: 'running',
        exitCode: null,
        signal: null,
        timeoutMs: p.timeoutMs,
        outdir: p.outdirWin,
        outdirWsl: p.outdirWsl,
        dir: p.dir,
        engineMode: p.engineMode,
        parsed: null,
        parseError: null,
        lastException: null,
        script: p.sp.win,
        scriptStaging: p.sp.staging || null,
        scriptFile: p.scriptFileInfo,
        inputFile: p.inputFileInfo,
        args: p.args,
        stage: null,
        stageAt: null,
        stageName: null,
        lastOutputAt: Date.now(),
        lines: 0,
        logBytes: 0,
        resultPath: null,
        resultBytes: 0,
        resultTruncated: false,
        pathWarnings: [],
        shots: null,
    };
    if (j.scriptStaging && j.scriptStaging.substituted) {
        const w = workdirStagingWarning(j.scriptStaging);
        if (w)
            j.pathWarnings.push(w);
    }
    return j;
}
/** Final stdout/stderr parsing (HEADLESS / DSH_SHOTS / path audit) */
export function collectJobOutputs(j, p) {
    try {
        const txt = fs.readFileSync(p.outPath, 'utf8');
        // v0.9.3: a parse failure no longer overwrites raw -- resultParseError is recorded separately and stdoutTail keeps the original text
        const lines = txt.split('\n').filter((l) => l.indexOf('HEADLESS ') === 0);
        if (lines.length) {
            const lastHead = lines[lines.length - 1].slice('HEADLESS '.length).trim();
            try {
                j.parsed = JSON.parse(lastHead);
            }
            catch (e) {
                j.parseError = { message: errorMessage(e).slice(0, 200), line: lastHead.slice(0, 400) };
            }
        }
        const sl = txt.split('\n').filter((l) => l.indexOf('DSH_SHOTS ') === 0);
        if (sl.length) {
            try {
                j.shots = JSON.parse(sl[sl.length - 1].slice('DSH_SHOTS '.length).trim());
            }
            catch (e) {
                /* ignore */
            }
        }
        j.stdoutTail = txt.length > 4000 ? txt.slice(-4000) : txt;
        j.pathWarnings = pathAudit(txt, '');
        // F-09: the job path likewise must not silently "succeed without opening a file" (same guard semantics as the sync path)
        j.warnings = (j.pathWarnings || [])
            .concat(sceneHygieneAudit(txt, ''))
            .concat(!p.fileOpt || p.fileLooksPython ? [noInputFileWarning(p.fileLooksPython)] : []);
    }
    catch (e) {
        /* ignore */
    }
    try {
        const er = fs.readFileSync(p.errPath, 'utf8');
        j.stderrTail = er.length > 2000 ? er.slice(-2000) : er;
        const m = er.match(/^[\w.]*(?:Error|Exception|Warning)\b.*$/gm);
        if (m && m.length)
            j.lastException = m[m.length - 1].slice(0, 300);
        if (j.pathWarnings.length === 0)
            j.pathWarnings = pathAudit('', er);
    }
    catch (e) {
        /* ignore */
    }
    // v0.9.6: pathAudit overwrites wholesale -- restore the "workDir is not shared, the script landed elsewhere" item (appended at the end)
    if (j.scriptStaging &&
        j.scriptStaging.substituted &&
        !(j.pathWarnings || []).some((w) => w && w.code === 'WORKDIR_NOT_SHARED')) {
        const w = workdirStagingWarning(j.scriptStaging);
        if (w)
            j.pathWarnings = (j.pathWarnings || []).concat([w]);
    }
}
/** Persist the result + final summary + ledger (still queryable after a backend restart) */
export function persistJobResult(d, j, p, opts) {
    const E = d.E;
    // v0.9.3: job results also persist via out_json (>4KB handled automatically), the same scheme as headless
    try {
        if (j.parsed !== null && j.parsed !== undefined) {
            const s = JSON.stringify(j.parsed);
            j.resultBytes = s.length;
            if (opts.outJson) {
                const t = E.readScriptPath(String(opts.outJson));
                fs.mkdirSync(path.dirname(t.wsl), { recursive: true });
                fs.writeFileSync(t.wsl, s, 'utf8');
                j.resultPath = t.win;
                j.resultPathWsl = t.wsl;
            }
            else if (s.length > 4000) {
                const dd = d.E.dumpResult(j.parsed, p.id);
                j.resultPath = dd.path;
                j.resultPathWsl = dd.path ? winToWsl(dd.path) : null;
            }
            j.resultTruncated = !!(j.resultPath && s.length > 4000);
        }
    }
    catch (e) {
        /* ignore */
    }
    // v0.8.10: persist the final summary + append to the ledger (still queryable after a backend restart)
    try {
        const arts = jobArtifacts(j).slice(0, 20);
        const summary = {
            id: p.id,
            kind: 'job',
            status: j.status,
            exitCode: j.exitCode,
            signal: j.signal,
            startedAt: j.startedAt,
            finishedAt: Date.now(),
            ms: Date.now() - j.startedAt,
            outdir: p.outdirWin,
            script: p.sp.win,
            engine: p.engineMode,
            runId: p.runId,
            file: p.fileOpt === undefined ? null : String(p.fileOpt),
            inputFile: j.inputFile, // F-09
            stage: j.stageName || null,
            artifacts: arts.map((a) => a.name + '(' + a.bytes + 'B)'),
            resultSummary: j.parsed ? JSON.stringify(j.parsed).slice(0, 400) : null,
            lastException: j.lastException || null,
            pluginVersion: PLUGIN_VERSION,
        };
        try {
            fs.writeFileSync(path.join(j.dir, 'summary.json'), JSON.stringify(summary, null, 1), 'utf8');
        }
        catch (e) {
            /* ignore */
        }
        d.ledgerAppend(Object.assign({}, summary, { artifacts: arts.slice(0, 8).map((a) => a.name) }));
    }
    catch (e) {
        /* ignore */
    }
}
//# sourceMappingURL=args.js.map