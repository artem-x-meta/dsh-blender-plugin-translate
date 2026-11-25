/** blender_rt_do receipt assembly: the text of ACT / headless session exec / see (v2.6.2 wording kept verbatim). */
import { text } from '../../contracts/dynamic.js';
import { redactSecrets } from '../errors.js';
const LF = String.fromCharCode(10);
export function formatSessionExec(res, nm) {
    const parts = ['ACT(session=' + nm + ') ok · ' + text(res.ms) + 'ms'];
    if (res.stdout && String(res.stdout).trim())
        parts.push('stdout: ' + redactSecrets(res.stdout).slice(0, 3000));
    if (res.stderr && String(res.stderr).trim())
        parts.push('stderr: ' + redactSecrets(res.stderr).slice(0, 1200));
    return parts;
}
export function formatSessionSee(res, spec) {
    return ('SEE(session) ' +
        text(spec.width) +
        'x' +
        text(spec.height) +
        ' · ' +
        text(res.ms) +
        'ms' +
        (res.coverage_estimate === null || res.coverage_estimate === undefined
            ? ''
            : ' · coverage ' + (Number(res.coverage_estimate) * 100).toFixed(2) + '%'));
}
export function formatActText(r) {
    const parts = [];
    parts.push('ACT ok · ' + text(r.ms) + 'ms');
    if (Number(r.mainThreadMs) > 1000)
        parts.push('⚠️ this call occupied the Blender main thread for about ' +
            text(r.mainThreadMs) +
            'ms — jobs over ~1s are better routed through blender_rt_headless / blender_rt_worker (no GUI stall)');
    if (r.stderr && String(r.stderr).trim())
        parts.push('stderr: ' + redactSecrets(r.stderr).slice(0, 1200));
    if (r.traceback)
        parts.push('--- traceback ---' + LF + redactSecrets(r.traceback).slice(0, 2000));
    if (r.stdout)
        parts.push('stdout: ' + redactSecrets(r.stdout).slice(0, 3000));
    return parts;
}
//# sourceMappingURL=envelope.js.map
