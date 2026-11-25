/** Registration aggregate for the 15 model tools (order matches the original inside v2.6.2 apply; each tool carries its own ctx.effect key). */
import { registerSee } from './see/index.js';
import { registerDo } from './do/index.js';
import { registerWatch } from './watch/index.js';
import { registerCmd } from './cmd.js';
import { registerCommands } from './commands.js';
import { registerLoop } from './loop/index.js';
import { registerPerf } from './perf.js';
import { registerOpt } from './opt.js';
import { registerHeadless } from './headless/index.js';
import { registerPlan } from '../plan/tool.js';
import { registerWorker } from './worker/index.js';
import { registerTxn } from './txn/index.js';
import { registerPreset } from './preset/index.js';
import { registerJob } from './job/index.js';
import { registerViewport } from './viewport/index.js';
export function registerTools(ctx, port) {
    // ---------- A. AI real-time interaction primitives ----------
    registerSee(ctx, port);
    registerDo(ctx, port);
    registerWatch(ctx, port);
    registerCmd(ctx, port);
    registerCommands(ctx, port);
    registerLoop(ctx, port);
    // ---------- performance / heavy work ----------
    registerPerf(ctx, port);
    registerOpt(ctx, port);
    registerHeadless(ctx, port);
    // ---------- contract layer / hot session ----------
    registerPlan(ctx, port);
    registerWorker(ctx, port);
    registerTxn(ctx, port);
    registerPreset(ctx, port);
    registerJob(ctx, port);
    // ---------- operations ----------
    registerViewport(ctx, port);
}
//# sourceMappingURL=index.js.map