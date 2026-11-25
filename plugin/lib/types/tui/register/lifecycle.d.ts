import type { TuiContext, TuiHostOptions, TuiServices } from '../types.js';
/** Register a polling loop that runs at a fixed interval for the lifetime of the host effect and never re-enters; the cleanup function it returns is managed by c.effect. */
export declare function every(c: TuiServices, ms: number, fn: () => Promise<void>, label: string): void;
/** ① selection → chip (toast optional: show it when there is one, attach the chip as usual otherwise) */
export declare function registerSelectionSurface(host: TuiContext, opts: TuiHostOptions, tag: string): void;
/** ② footer field (tuiStatus.setField is a newer dsh-TUI seam: old versions only have set(), so this does not degrade to a whole status row) */
export declare function registerStatusSurface(host: TuiContext, opts: TuiHostOptions, tag: string): void;
