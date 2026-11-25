import type { TuiHostOptions } from './types.js';
export declare const SUBCOMMANDS: {
    name: string;
    description: string;
}[];
/** '/blender <sub>' → text. Exported for self-checks. */
export declare function blenderCommand(rawInput: string, opts: TuiHostOptions, signal?: AbortSignal): Promise<{
    kind: string;
    text: string;
}>;
