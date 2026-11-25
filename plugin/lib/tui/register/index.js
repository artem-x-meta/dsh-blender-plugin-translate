/** tui/register: mount each TUI half on the service blocks the host injects; blocks whose service the host does not have are never enabled. */
import { bridge, wired } from '../state.js';
import { registerSelectionSurface, registerStatusSurface } from './lifecycle.js';
import { registerCommandSurface, registerMentionsSurface } from './commands.js';
/** apply() calls this; blocks whose service the host does not have are never enabled. */
export function registerTuiHost(ctx, opts) {
    const host = ctx;
    if (!host || typeof host.inject !== 'function')
        return;
    const tag = 'dsh-blender-plugin: tui ';
    // ①② selection chip / footer (continuously polled seams)
    registerSelectionSurface(host, opts, tag);
    registerStatusSurface(host, opts, tag);
    // ③④ @ mentions / /blender command and subcommand completion
    registerMentionsSurface(host, opts, tag);
    registerCommandSurface(host, opts, tag);
}
/** one doctor line: which seams the TUI host half is wired to (explains why it is empty on a non-dsh-TUI host) */
export function tuiHostSummary() {
    const on = (b) => (b ? '✅' : '—');
    if (!wired.chips && !wired.status && !wired.mentions && !wired.commandTree) {
        return ('TUI host half: not enabled (this is not a dsh-TUI host, or that dsh-TUI version has none of these seams; model tools are unaffected)' +
            (wired.commands ? ' · /blender command ✅' : ''));
    }
    let s = 'TUI host half: selection chip ' +
        on(wired.chips) +
        ' · footer ' +
        on(wired.status) +
        ' · @ mentions ' +
        on(wired.mentions) +
        ' · /blender ' +
        on(wired.commands);
    if (bridge.lastAt)
        s +=
            ' · last selection seq=' +
                String(bridge.lastSeq) +
                (bridge.lastOk ? ' wired' : ' not wired (' + String(bridge.lastReason || '') + ')');
    return s;
}
//# sourceMappingURL=index.js.map
