/** Headless human-readable summary (block 1): assembled segment by segment per the v0.9.2 narrative caliber (order identical to v2.6.2). */
import { clipText, safeStringify } from '../../ui/cards.js';
import { redactSecrets } from '../../tools/errors.js';
import { asRecord, isRecord, text } from '../../contracts/dynamic.js';
const NLx = String.fromCharCode(10);
export function headlessHumanText(res, ctx) {
    const r = asRecord(res);
    const parts = [];
    const okFlag = okFlagOf(r);
    parts.push(statusLine(r, okFlag));
    if (ctx && ctx.mode === 'job')
        parts.push('mode: job layer (jobId=' + text(ctx.jobId) + ', completed within the wait window)');
    pushBasic(parts, r);
    pushEngine(parts, r);
    if (r.stage || r.stageName)
        parts.push('last stage (stage): ' + String(safeStringify(r.stage || r.stageName)));
    if (r.lastException)
        parts.push('last exception: ' + text(r.lastException));
    if (r.logs) {
        const logs = asRecord(r.logs);
        parts.push('logs: ' + text(logs.stdout) + ' · ' + text(logs.stderr));
    }
    pushResult(parts, r);
    pushShots(parts, r);
    pushPathWarnings(parts, r);
    pushWarnings(parts, r);
    pushStdout(parts, r);
    pushStderr(parts, r);
    pushExpect(parts, r);
    pushArtifacts(parts, r);
    if (r.noiseFiltered)
        parts.push('(filtered out ' + text(r.noiseFiltered) + ' noise artifacts)');
    if (r.hint)
        parts.push('hint: ' + text(r.hint));
    if (r.traceback)
        parts.push('--- traceback ---' + NLx + redactSecrets(r.traceback).slice(0, 1200));
    if (typeof r.id === 'string' && r.id.indexOf('job-') === 0)
        parts.push('job id: ' + r.id + ' (runId=' + text(r.runId || '-') + ')');
    if (r.runId)
        parts.push('run id: ' +
            text(r.runId) +
            ' (queryable with blender_rt_job(op="status"/"collect"/"wait", id=…); still findable in the on-disk ledger after a backend restart)');
    const notes = ctx.notes;
    if (Array.isArray(notes))
        for (const n of notes)
            parts.push('· ' + text(n));
    return parts.join(NLx);
}
function okFlagOf(r) {
    return typeof r.ok === 'boolean'
        ? r.ok
        : r.status === 'done' || r.status === 'finished'
            ? true
            : r.status === 'failed' ||
                r.status === 'killed' ||
                r.status === 'timeout' ||
                r.status === 'stale'
                ? false
                : null;
}
function statusLine(r, okFlag) {
    const st = r.status || (okFlag ? 'finished' : 'unknown');
    return ((okFlag === true ? 'HEADLESS ok' : okFlag === false ? 'HEADLESS failed' : 'HEADLESS running') +
        ' · status=' +
        text(st) +
        (r.exitCode === undefined || r.exitCode === null ? '' : ' · exit=' + text(r.exitCode)) +
        (r.timedOut ? ' · killed on timeout' : '') +
        (typeof r.ms === 'number' ? ' · ' + String(r.ms) + 'ms' : '') +
        (r.reason ? ' · ' + text(r.reason) : ''));
}
function pushBasic(parts, r) {
    if (r.failure_hint)
        parts.push('hint: ' + text(r.failure_hint));
    if (r.session)
        parts.push('session: ' + text(r.session));
    if (r.script)
        parts.push('script: ' + text(r.script));
    if (r.scriptFile) {
        const sf = asRecord(r.scriptFile);
        parts.push('script file: ' + text(sf.resolved || sf.given) + ' (' + text(sf.bytes) + ' bytes)');
    }
    const inputFile = asRecord(r.inputFile);
    if (inputFile.md5)
        parts.push('input file: ' +
            text(inputFile.path) +
            ' · ' +
            text(inputFile.size) +
            ' bytes · mtime=' +
            text(inputFile.mtime || inputFile.mtimeMs) +
            ' · md5=' +
            text(inputFile.md5) +
            (inputFile.md5Partial ? ' (partial hash)' : ''));
}
function pushEngine(parts, r) {
    const gpu = asRecord(r.gpu);
    const gpuAfter = asRecord(gpu.after);
    const engName = r.engine || (gpu.after && gpuAfter.engine) || null;
    if (engName)
        parts.push('engine: ' + text(engName) + (r.engineMode ? ' (mode=' + text(r.engineMode) + ')' : ''));
    if (r.gpu) {
        const g = gpu;
        parts.push('GPU: ' +
            (g.fell_back_to_cpu
                ? '⚠️ fell back to CPU (' +
                    text(g.error || (g.before && asRecord(g.before).device_type) || '') +
                    ')'
                : '✅ ' +
                    text(gpuAfter.device_type || g.configured || '') +
                    ' · ' +
                    String((gpuAfter.gpu_enabled || []).join(','))) +
            (g.configured ? ' · auto-configured this run as ' + text(g.configured) : ''));
    }
}
function pushResult(parts, r) {
    const rj = r.resultJson !== undefined ? r.resultJson : r.result;
    if (rj !== null && rj !== undefined) {
        const s = safeStringify(rj) || '';
        parts.push('result: ' +
            (s.length > 6000
                ? s.slice(0, 6000) + NLx + '…[result is ' + String(s.length) + ' chars in total; see resultPath for the full text]'
                : s));
    }
    if (r.resultPath)
        parts.push('result written to disk: ' +
            text(r.resultPath) +
            (r.resultPathWsl ? ' (WSL: ' + text(r.resultPathWsl) + ')' : '') +
            ' · ' +
            text(r.resultBytes || 0) +
            ' bytes, full JSON');
    if (r.resultParseError) {
        const pe = asRecord(r.resultParseError);
        parts.push('⚠️ the final HEADLESS line is not valid JSON (**the raw output was kept**, see stdout below) · ' +
            text(pe.message) +
            NLx +
            '  that line: ' +
            text(pe.line).slice(0, 300));
    }
}
function pushShots(parts, r) {
    const shots = asRecord(r.shots);
    const shotRows = Array.isArray(shots.rows) ? shots.rows : [];
    if (shotRows.length) {
        parts.push('shots (' +
            String(shotRows.length) +
            ' images, coverage = share of non-background pixels): ' +
            NLx +
            shotRows
                .map((x) => {
                const row = asRecord(x);
                const warning = asRecord(row.warning);
                return ('  · ' +
                    text(row.name) +
                    ' · ' +
                    text(row.ms) +
                    'ms · ' +
                    text(row.bytes) +
                    'B · md5=' +
                    text(row.md5) +
                    (typeof row.coverage_estimate === 'number'
                        ? ' · coverage=' + (row.coverage_estimate * 100).toFixed(2) + '%'
                        : '') +
                    (row.warning ? '  ⚠️ ' + text(warning.hint || warning.code) : ''));
            })
                .join(NLx));
        if (shots.jsonl)
            parts.push('shots jsonl: ' + text(shots.jsonl));
    }
    else if (shots.error)
        parts.push('⚠️ shots failed: ' + text(shots.error));
}
function pushPathWarnings(parts, r) {
    if (!Array.isArray(r.pathWarnings) || !r.pathWarnings.length)
        return;
    parts.push('⚠️ path health check (' +
        String(r.pathWarnings.length) +
        ' entries): ' +
        NLx +
        r.pathWarnings
            .map((w) => {
            const warning = asRecord(w);
            return ('  · ' +
                text(warning.code) +
                ' · ' +
                text(warning.evidence || warning.value || '') +
                NLx +
                '    ' +
                text(warning.hint));
        })
            .join(NLx));
}
function pushWarnings(parts, r) {
    if (!Array.isArray(r.warnings) || !r.warnings.length)
        return;
    parts.push('⚠️ warnings (' +
        String(r.warnings.length) +
        ' entries): ' +
        NLx +
        r.warnings
            .map((w) => {
            const warning = asRecord(w);
            return ('  · ' +
                (isRecord(w)
                    ? text(warning.code) + (warning.hint ? ' — ' + text(warning.hint) : JSON.stringify(w))
                    : text(w)));
        })
            .join(NLx));
}
function pushStdout(parts, r) {
    if (r.stdoutTruncated)
        parts.push('(stdout truncated: see the logs path / resultPath for the full text)');
    const so = String(r.stdoutTail !== undefined && r.stdoutTail !== null ? r.stdoutTail : r.stdout || '');
    if (!so)
        return;
    const rj = r.resultJson !== undefined ? r.resultJson : r.result;
    parts.push((r.stdoutTruncated ? '--- stdout tail (truncated) ---' : '--- stdout ---') +
        NLx +
        (rj !== null && rj !== undefined
            ? clipText(redactSecrets(so), 500, 800)
            : clipText(redactSecrets(so), 1500, 2500)));
}
function pushStderr(parts, r) {
    const se = String(r.stderrTail !== undefined && r.stderrTail !== null ? r.stderrTail : r.stderr || '');
    if (se.trim())
        parts.push('--- stderr (head+tail) ---' + NLx + clipText(redactSecrets(se), 500, 1500));
}
function pushExpect(parts, r) {
    if (!r.expect)
        return;
    const ex = asRecord(r.expect);
    const observed = asRecord(ex.observed);
    const deltaRaw = observed.delta;
    const delta = asRecord(deltaRaw);
    const before = asRecord(observed.before);
    const after = asRecord(observed.after);
    parts.push('expect check: ' +
        (ex.ok ? '✅ passed' : '❌ **failed**') +
        (deltaRaw
            ? ' · new objects ' +
                text(delta.objects) +
                ' / meshes ' +
                text(delta.meshes) +
                ' (before ' +
                text(before.objects) +
                ' → after ' +
                text(after.objects) +
                ')'
            : '') +
        (Array.isArray(ex.warnings) && ex.warnings.length
            ? NLx + '  ' + ex.warnings.join(NLx + '  ')
            : ''));
}
function pushArtifacts(parts, r) {
    const arts = Array.isArray(r.artifacts) ? r.artifacts : [];
    if (!arts.length)
        return;
    parts.push('artifacts: ' +
        arts
            .slice(0, 12)
            .map((a) => {
            if (typeof a === 'string')
                return a;
            const art = asRecord(a);
            return text(art.name) + '(' + text(art.bytes) + 'B' + (art.fresh ? ' new' : '') + ')';
        })
            .join(' · '));
}
//# sourceMappingURL=human-text.js.map