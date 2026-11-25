import type { HostContext } from '../host/context.js';
export declare const ANY_SCHEMA: Record<string, unknown>;
export declare const HINT_KERNEL = "Persistent kernel: K.x = 1 set in this call is still readable in the next one; bpy / math / mathutils / Vector are preloaded.";
/**
 * v1.0.1 (issue #10): the **degraded exit** when schemastery parsing fails.
 * The goal is not "it can still do some work" but **making the failure readable and locatable**: the placeholder tools still appear in the tool list,
 * and calling one immediately reports the names that were tried, the real error of each channel and how to fix it -- rather than, as in the old version,
 * "throw during module load -> all 15 tools disappear at once + the host only replies failed to import".
 */
export declare function registerSchemaDiagnostic(ctx: HostContext): void;
