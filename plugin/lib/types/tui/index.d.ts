/**
 * Facade for the dsh-TUI host half.
 *
 * The implementation is split along seams under ./tui/: http, state, selection, footer, mentions, commands, register/*.
 * This file keeps only the original import names (the former src/tui-host.ts has been deleted); the plugin entry point and tests now import from here.
 */
export type { TuiHostOptions, MentionItem } from './types.js';
export { subSelectionText, selectionMessageText, selectionChipTitle, selectionTick, } from './selection.js';
export { footerField } from './footer.js';
export { mentionItems, filterMentionItems, createSceneMentionSource } from './mentions.js';
export { blenderCommand } from './commands.js';
export { registerTuiHost, tuiHostSummary } from './register/index.js';
export declare const __tuiHostInternals: {
    wired: import("./state.js").WiredState;
    bridge: import("./state.js").BridgeState;
    SUBCOMMANDS: {
        name: string;
        description: string;
    }[];
};
