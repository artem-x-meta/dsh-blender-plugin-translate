/** preset execution layer: argument coercion (including data JSON parsing) -> POST /preset -> text rendering. */
import { ensureBackend } from '../../host/backend/index.js';
import { backendPost, leasedText } from '../../host/http.js';
import { asRecord, text } from '../../contracts/dynamic.js';
import { redactSecrets, toolError } from '../errors.js';
import { formatPreset } from './response.js';
export async function executePreset(port, args) {
    if (!(await ensureBackend(port)))
        return toolError('backend_unreachable', 'Backend unavailable (127.0.0.1:' + String(port) + ')', 'Run blender_viewport op=start to bring the backend up, then retry');
    const op = text(args.op) || 'list';
    const built = buildPresetArgs(args);
    if ('error' in built)
        return built.error;
    const r = await backendPost(port, '/preset', { op: op, args: built.args }, 300000);
    const lt = leasedText(r);
    if (lt)
        return { text: lt };
    if (!r || r.ok !== true)
        return toolError('backend_error', 'PRESET ' + op + ' failed · ' + redactSecrets(text(r.error || r.raw || 'unknown')), 'Check the preset data and op');
    return { text: formatPreset(op, asRecord(r.result)) };
}
function splitList(v) {
    return String(v)
        .split(',')
        .map((x) => x.trim())
        .filter(Boolean);
}
function buildPresetArgs(args) {
    const a = {};
    if (text(args.name))
        a.name = text(args.name);
    if (text(args.kind))
        a.kind = text(args.kind);
    if (text(args.note))
        a.note = text(args.note);
    if (text(args.path))
        a.path = text(args.path);
    if (text(args.tags))
        a.tags = splitList(args.tags);
    if (text(args.names))
        a.names = splitList(args.names);
    if (text(args.targets))
        a.targets = splitList(args.targets);
    if (args.data) {
        try {
            a.data = JSON.parse(String(args.data));
        }
        catch (e) {
            return {
                error: toolError('invalid_params', 'data is not valid JSON: ' + (e instanceof Error ? e.message.slice(0, 120) : 'unknown'), 'Pass a JSON object string, e.g. data={"k":1}'),
            };
        }
    }
    if (args.overwrite === false)
        a.overwrite = false;
    return { args: a };
}
//# sourceMappingURL=execute.js.map