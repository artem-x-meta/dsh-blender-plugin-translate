import type { ChildProcess } from 'node:child_process';
import { writeHeadlessScript } from '../staging.js';
import type { LaunchOpts } from './resolve.js';
export interface LaunchPlan {
    sp: ReturnType<typeof writeHeadlessScript>;
    args: string[];
    childEnv: Record<string, string | undefined>;
}
/** Write the boot script and assemble the args and child env (dryRun needs these first too) */
export declare function buildLaunchPlan(opts: LaunchOpts, statusWsl: string): LaunchPlan;
/** Detached spawn; spawning a nonexistent executable does not throw but emits 'error' asynchronously (without a handler it takes the backend down) */
export declare function spawnDetachedBlender(exe: string, args: string[], childEnv: Record<string, string | undefined>): {
    child: ChildProcess | null;
    spawnErrRef: {
        value: unknown;
    };
};
