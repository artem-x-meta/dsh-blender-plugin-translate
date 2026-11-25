/** tui/register/commands: the three parts -- @ mentions, the /blender command, and dsh-TUI subcommand completion. */
import { createSceneMentionSource } from '../mentions.js';
import { SUBCOMMANDS, blenderCommand } from '../commands.js';
import { wired } from '../state.js';
/** ③ @ mentions */
export function registerMentionsSurface(host, opts, tag) {
    host.inject(['tuiMentions'], (c) => {
        const mentions = c.tuiMentions;
        if (!mentions || typeof mentions.register !== 'function')
            return;
        c.effect(() => {
            let dispose;
            const complete = createSceneMentionSource(opts.port);
            // register throws outright on invalid / duplicate / over-limit input (same criterion as tuiCommandTrees): if it cannot register, treat the part as absent
            try {
                dispose = mentions.register({ id: 'blender', title: 'Blender', complete: complete });
            }
            catch {
                dispose = undefined;
            }
            wired.mentions = typeof dispose === 'function';
            return () => {
                wired.mentions = false;
                if (typeof dispose === 'function')
                    dispose();
            };
        }, tag + 'mentions');
    });
}
/** ④ the /blender command (a DSH core seam; the Web side has it too) + dsh-TUI subcommand completion */
export function registerCommandSurface(host, opts, tag) {
    host.inject(['commands'], (c) => {
        const commands = c.commands;
        if (!commands || typeof commands.register !== 'function')
            return;
        c.effect(() => {
            wired.commands = true;
            const dispose = commands.register({
                name: 'blender',
                description: 'Blender channel: status / doctor / jobs',
                input: { hint: 'status | doctor | jobs' },
                handler: (inv) => blenderCommand(inv.rawInput ?? '', opts, inv.signal),
            });
            return () => {
                wired.commands = false;
                if (typeof dispose === 'function')
                    dispose();
            };
        }, tag + 'command');
    });
    host.inject(['tuiCommandTrees'], (c) => {
        const trees = c.tuiCommandTrees;
        if (!trees || typeof trees.register !== 'function')
            return;
        c.effect(() => {
            wired.commandTree = true;
            let dispose;
            try {
                dispose = trees.register({
                    root: 'blender',
                    children: (path) => (path.length === 1 ? SUBCOMMANDS : []),
                });
            }
            catch {
                dispose = undefined;
            }
            return () => {
                wired.commandTree = false;
                if (typeof dispose === 'function')
                    dispose();
            };
        }, tag + 'command tree');
    });
}
//# sourceMappingURL=commands.js.map