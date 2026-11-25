import fs from 'node:fs';
import path from 'node:path';
import { winToWsl } from '../../config.js';
import { errorMessage } from '../../core/json.js';
import { noInputFileWarning } from '../../file_guard.js';
import { workdirStagingWarning } from '../../proc_env.js';
/** The engine field in the GPU receipt (Python-side JSON, dynamic shape) */
export function gpuAfterEngine(gpu) {
    if (!gpu)
        return null;
    const after = gpu.after;
    if (!after || typeof after !== 'object')
        return null;
    return after.engine || null;
}
/** Dynamic boundary parsing: read a field of the named group object from the expect observation (the JSON comes from the Python side, shape decided by the script) */
function objField(rec, group, field) {
    if (!rec)
        return null;
    const g = rec[group];
    if (!g || typeof g !== 'object')
        return null;
    const v = g[field];
    return v === undefined ? null : v;
}
function deltaObjects(rec) {
    return objField(rec, 'delta', 'objects') || 0;
}
function taggedLines(stdout, tag) {
    return stdout.split('\n').filter((l) => l.indexOf(tag) === 0);
}
function lastTaggedPayload(stdout, tag) {
    const lines = taggedLines(stdout, tag);
    return lines.length ? lines[lines.length - 1].slice(tag.length).trim() : null;
}
export function parseHeadlessStdout(stdout) {
    // ---- result contract: HEADLESS <single-line JSON> (take the last one)
    // v0.9.3: when the last line is not valid JSON it **no longer overrides raw** (older versions returned {_parse_error, raw} and displaced the real output,
    // so the caller could only see "_parse_error: Unexpected token 'O'"). Now parsed stays null, the parse failure is recorded separately in
    // resultParseError, and the original stdout (stdoutTail / logs) is preserved as-is.
    let parsed = null;
    let parseError = null;
    const head = lastTaggedPayload(stdout, 'HEADLESS ');
    if (head !== null) {
        try {
            parsed = JSON.parse(head);
        }
        catch (e) {
            parseError = { message: errorMessage(e).slice(0, 200), line: head.slice(0, 400) };
        }
    }
    // ---- v0.9.3: shots receipt (DSH_SHOTS <single-line JSON>)
    let shotsRes = null;
    const shot = lastTaggedPayload(stdout, 'DSH_SHOTS ');
    if (shot !== null) {
        try {
            shotsRes = JSON.parse(shot);
        }
        catch (e) {
            shotsRes = { ok: false, parse_error: errorMessage(e).slice(0, 200) };
        }
    }
    // ---- GPU receipt (the preamble prints DSH_GPU)
    let gpu = null;
    const g = lastTaggedPayload(stdout, 'DSH_GPU ');
    if (g !== null) {
        try {
            gpu = JSON.parse(g);
        }
        catch (e) {
            gpu = { _parse_error: errorMessage(e) };
        }
    }
    return { parsed, parseError, shotsRes, gpu };
}
export function evaluateExpect(exp, stdout) {
    if (!exp)
        return null;
    let observed = null;
    const payload = lastTaggedPayload(stdout, 'DSH_EXPECT ');
    if (payload !== null) {
        try {
            observed = JSON.parse(payload);
        }
        catch (e) {
            observed = null;
        }
    }
    const expectEval = { spec: exp, observed: observed, ok: true, warnings: [] };
    const minNew = Number(exp.minNewObjects !== undefined ? exp.minNewObjects : exp.min_new_objects);
    if (!observed || observed.error) {
        expectEval.ok = false;
        expectEval.warnings.push('expect observation failed: ' + ((observed && observed.error) || 'no DSH_EXPECT line'));
    }
    else if (Number.isFinite(minNew) && Number(deltaObjects(observed)) < minNew) {
        expectEval.ok = false;
        expectEval.warnings.push('object count fell short of expectations: before=' +
            String(objField(observed, 'before', 'objects')) +
            ' → after=' +
            String(objField(observed, 'after', 'objects')) +
            ' (required new ≥' +
            minNew +
            ') — a typical empty build run');
    }
    return expectEval;
}
export { collectArtifacts } from './artifacts.js';
export { classifyFailure, extractFailureContext, failureHint } from './failure.js';
export function summarizeShots(shotsRes) {
    const rowsIn = Array.isArray(shotsRes.views) ? shotsRes.views : [];
    const rows = rowsIn.map((x) => {
        const e = x && typeof x === 'object' ? x : {};
        const frame = e.frame && typeof e.frame === 'object' ? e.frame : null;
        const cov = frame && typeof frame.coverage === 'number' ? frame.coverage : null;
        const row = {
            name: e.view || null,
            path: e.path || null,
            ms: e.ms || null,
            bytes: e.bytes || null,
            md5: e.hash || null,
            res: e.res || null,
            device: e.device || null,
            coverage_estimate: cov,
        };
        if (cov !== null && cov < 0.05) {
            row.warning = {
                code: 'subject_too_small',
                coverage_estimate: cov,
                hint: 'the subject fills only ' +
                    (cov * 100).toFixed(2) +
                    '% of the frame — details are unreadable from this viewpoint: move from closer / change look_at / ' +
                    'add targets=[name] for this shot or shrink the framing with focus="x,y,z,r" (the same criterion as rt_see)',
            };
        }
        return row;
    });
    const covs = rows
        .map((r) => r.coverage_estimate)
        .filter((x) => typeof x === 'number');
    return {
        ok: !!shotsRes.ok,
        count: rows.length,
        rows: rows,
        coverage_min: covs.length ? Math.min.apply(null, covs) : null,
        outdir: shotsRes.outdir || null,
        jsonl: shotsRes.jsonl || null,
        total_ms: shotsRes.total_ms || null,
        render_ms: shotsRes.render_ms || null,
        engine: shotsRes.engine || null,
        samples: shotsRes.samples || null,
        device_line: shotsRes.device_line || null,
        unknown_views: shotsRes.unknown_views || null,
        scope_warnings: shotsRes.scope_warnings || null,
        error: shotsRes.error ||
            (shotsRes.ok === false ? shotsRes.hint || 'shots failed (see error/traceback)' : null),
    };
}
/** Shots-only runs have no HEADLESS result; synthesize the same shape as a full result. */
export function applyShotsResult(parsed, shots) {
    if (!shots || parsed !== null)
        return parsed;
    return {
        ok: !!shots.ok,
        shots: shots.rows,
        outdir: shots.outdir,
        jsonl: shots.jsonl,
        count: shots.count,
        coverage_min: shots.coverage_min,
        error: shots.error,
    };
}
/** Merge path audit, scene hygiene and the no-input warning into the run record order. */
export function finishRunWarnings(pathWarnings, hygieneWarnings, fileOpt, fileLooksPython) {
    const noFile = !fileOpt || fileLooksPython ? [noInputFileWarning(fileLooksPython)] : [];
    return (pathWarnings || []).concat(hygieneWarnings).concat(noFile);
}
/** Append the workDir-not-shared warning once, preserving pathAudit's original ordering. */
export function withWorkdirWarning(pathWarnings, staging) {
    if (!staging ||
        !staging.substituted ||
        pathWarnings.some((w) => typeof w === 'object' &&
            w !== null &&
            w.code === 'WORKDIR_NOT_SHARED')) {
        return pathWarnings;
    }
    const w = workdirStagingWarning(staging);
    if (w)
        pathWarnings.push(w);
    return pathWarnings;
}
export function writeResultJson(parsed, opts, d, runId) {
    // ---- v0.9.1 (93-A3): structured result to disk (automatic above 4KB, or a path given via outJson=) — no more indexOf slicing of stdout
    const outJsonInfo = { path: null, bytes: 0, wsl: null };
    try {
        if (parsed !== null && parsed !== undefined) {
            const s = JSON.stringify(parsed);
            outJsonInfo.bytes = s.length;
            if (opts.outJson) {
                const t = d.readScriptPath(String(opts.outJson));
                fs.mkdirSync(path.dirname(t.wsl), { recursive: true });
                fs.writeFileSync(t.wsl, s, 'utf8');
                outJsonInfo.path = t.win;
                outJsonInfo.wsl = t.wsl; // one copy in Windows form + one in WSL-visible form
            }
            else if (s.length > 4000) {
                const dump = d.dumpResult(parsed, runId);
                outJsonInfo.path = dump.path;
                outJsonInfo.bytes = dump.bytes;
                outJsonInfo.wsl = outJsonInfo.path ? winToWsl(outJsonInfo.path) : null; // give both forms
            }
        }
    }
    catch (e) {
        /* a failed write does not affect the main result */
    }
    return outJsonInfo;
}
//# sourceMappingURL=result.js.map