import type { TuiContext, TuiHostOptions } from '../types.js';
/** (3) @ mentions */
export declare function registerMentionsSurface(host: TuiContext, opts: TuiHostOptions, tag: string): void;
/** (4) /blender command (a DSH core seam; the Web also has it) + dsh-TUI subcommand completion */
export declare function registerCommandSurface(host: TuiContext, opts: TuiHostOptions, tag: string): void;
