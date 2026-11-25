// launch subprocess plan and detached spawn (split out of launch.ts)
import { spawn } from 'node:child_process';
import fs from 'node:fs';
import { wslToWin } from '../config.js';
import { USER_CONFIG_WIN, USER_SCRIPTS_WIN } from '../paths.js';
import { writeHeadlessScript } from '../staging.js';
import { baseChildEnv, withWslEnv } from '../proc_env.js';
import { LAUNCH_BOOT_PY } from './resolve.js';
/** Write the boot script, assemble the arguments and the child environment (even dryRun needs these first) */
export function buildLaunchPlan(opts, statusWsl) {
    const sp = writeHeadlessScript(LAUNCH_BOOT_PY);
    const args = ['--python', sp.win];
    if (opts.file)
        args.push(wslToWin(String(opts.file)));
    const childEnv = withWslEnv(baseChildEnv({}));
    if (USER_SCRIPTS_WIN)
        childEnv.BLENDER_USER_SCRIPTS = USER_SCRIPTS_WIN;
    if (USER_CONFIG_WIN)
        childEnv.BLENDER_USER_CONFIG = USER_CONFIG_WIN;
    if (opts.addonFile)
        childEnv.DSH_BLENDER_ADDON_FILE = String(opts.addonFile);
    if (opts.addonModule)
        childEnv.DSH_BLENDER_ADDON_MODULE = String(opts.addonModule);
    childEnv.DSH_BLENDER_LAUNCH_STATUS = wslToWin(statusWsl);
    try {
        fs.rmSync(statusWsl, { force: true });
    }
    catch (e) {
        /* failing to delete the old status file does not matter */
    }
    return { sp, args, childEnv };
}
/** detached spawn; spawning a non-existent executable does not throw, it emits 'error' asynchronously (without a handler it takes the backend down) */
export function spawnDetachedBlender(exe, args, childEnv) {
    const spawnErrRef = { value: null };
    let child = null;
    try {
        child = spawn(exe, args, { env: childEnv, stdio: 'ignore', detached: true });
    }
    catch (e) {
        spawnErrRef.value = e;
    }
    if (child) {
        // ⚠ measured pitfall (caught by the v0.9.4 self-check): spawning a non-existent executable **does not throw**, it emits 'error' asynchronously.
        child.on('error', (e) => {
            spawnErrRef.value = e;
        });
        try {
            child.unref();
        }
        catch (e) {
            /* ignore */
        }
    }
    else if (!spawnErrRef.value) {
        spawnErrRef.value = new Error('spawn returned an empty handle');
    }
    return { child, spawnErrRef };
}
//# sourceMappingURL=spawn.js.map