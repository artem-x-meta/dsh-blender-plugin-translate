import type { ChildProcess } from 'node:child_process';
/** Whether the child process is really still alive: when killed by a signal, exitCode stays null and only signalCode has a value */
export declare function childAlive(): boolean;
export declare function spawnChild(port: number): string;
/** stale-handle branch: the handle exists but the port is dead → stop the untrustworthy old handle per platform and return its pid. */
export declare function killStaleChild(): number | null;
export declare function getChild(): ChildProcess | null;
/** Kill and clear the current child-process handle; returns whether there was a handle at all (the caller writes the receipt from that). */
export declare function killChildHandle(): boolean;
