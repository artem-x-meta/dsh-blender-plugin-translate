// Job script build entry point (split): arguments / preamble / writing to disk
import { prepareJobArgs } from './args.js';
import { buildJobParts, finalizeJobArgs } from './preload.js';
export function buildJobScript(E, opts = {}) {
    const a = prepareJobArgs(E, opts);
    const built = buildJobParts(E, opts, a);
    finalizeJobArgs(a, built, opts);
    return {
        ...a,
        sp: built.sp,
        timeoutMs: built.timeoutMs,
    };
}
//# sourceMappingURL=index.js.map