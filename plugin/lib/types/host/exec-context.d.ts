import { AsyncLocalStorage } from 'node:async_hooks';
export interface ExecContextStore {
    signal?: AbortSignal;
}
export declare const EXEC_CTX: AsyncLocalStorage<ExecContextStore>;
/** The host exec.signal for the current tool call (undefined if there is none) */
export declare function execSignal(): AbortSignal | undefined;
