import { PLUGIN_VERSION } from '../../core/evidence.js';
import { USER_CONFIG_WIN, USER_SCRIPTS_WIN } from '../../paths.js';
import { baseChildEnv, withWslEnv } from '../../proc_env.js';
/** Build the child environment, including explicit env, WSL bridging and optional user Blender config. */
export function buildChildEnv(p, opts, sessionName) {
    const childEnv = baseChildEnv({
        DSH_RUN_ID: p.runId,
        DSH_OUTDIR: p.outdirWin,
        DSH_ARGS: JSON.stringify(Array.isArray(opts.args) ? opts.args.map(String) : []),
        DSH_SESSION: sessionName,
        DSH_PLUGIN_VERSION: PLUGIN_VERSION,
    });
    if (p.envOpt) {
        for (const k of Object.keys(p.envOpt))
            childEnv[String(k)] = String(p.envOpt[k]);
    }
    // ⚠ Measured trap (v0.9.1): when spawning a Windows blender.exe from the WSL side, **env does not cross the boundary automatically** —
    // Node passes DSH_* to spawn, yet the child sees none of them in os.environ (they must be declared via WSLENV).
    // It is declared here automatically; the script also injects it once more (belt and braces, see DSH_ENV_PRELUDE).
    withWslEnv(childEnv, p.envOpt || undefined);
    if (opts.useUserConfig) {
        if (USER_CONFIG_WIN)
            childEnv.BLENDER_USER_CONFIG = USER_CONFIG_WIN;
        if (USER_SCRIPTS_WIN)
            childEnv.BLENDER_USER_SCRIPTS = USER_SCRIPTS_WIN;
    }
    return childEnv;
}
//# sourceMappingURL=child-env.js.map