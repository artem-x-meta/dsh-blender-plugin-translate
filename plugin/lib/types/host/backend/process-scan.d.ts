/**
 * Scan /proc for "backends started by earlier generations of this plugin" and stop them via signal (SIGTERM by default).
 * A hot reload loses the child handle (held by the previous generation's fiber), and handles alone cannot stop the leftover processes -- this is the fallback.
 * v1.0.1: added the signal parameter (a process whose event loop is pinned by synchronous work only honors SIGKILL).
 */
export declare function killBackendByCmd(port: number, signal?: NodeJS.Signals): string[];
