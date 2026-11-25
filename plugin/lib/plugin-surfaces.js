/** Plugin external-seam assembly: the dsh-TUI host half and the 15 model tools. */
import { HOLDER } from './constants.js';
import { registerTools } from './tools/index.js';
import { registerTuiHost } from './tui/index.js';
export function registerTuiSurface(ctx, port, cfgIn) {
    // v2.6.1: dsh-TUI host half (contract v2.3 addendum). Each block is enabled if the seam exists; on Web / headless nothing is done.
    if (cfgIn.tui !== false)
        registerTuiHost(ctx, { port: port, holder: HOLDER });
}
export function registerToolSurface(ctx, port) {
    // ---------- tool surface: the 15 tools registered in the original v2.6.2 order (each tool's ctx.effect key is unchanged) ----------
    registerTools(ctx, port);
}
//# sourceMappingURL=plugin-surfaces.js.map