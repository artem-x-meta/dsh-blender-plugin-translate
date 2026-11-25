import type { TuiHostOptions } from '../types.js';
/** apply() calls this; a block whose corresponding host service is missing is never enabled. */
export declare function registerTuiHost(ctx: unknown, opts: TuiHostOptions): void;
/** One doctor line: which seams the TUI host half has connected (on a non-dsh-TUI host it explains why it is empty) */
export declare function tuiHostSummary(): string;
