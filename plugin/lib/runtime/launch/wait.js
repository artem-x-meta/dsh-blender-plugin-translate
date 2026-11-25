// Startup wait: addon port polling (split out of launch.ts)
import { probeTcp } from '../backend_probe.js';
/** Wait until the addon port is listening; started is the start time (ms) */
export async function waitForAddonPort(started, waitMs, addonPort) {
    while (Date.now() - started < waitMs) {
        if (await probeTcp('127.0.0.1', addonPort, 700))
            return true;
        await new Promise((r) => setTimeout(r, 500));
    }
    return false;
}
//# sourceMappingURL=wait.js.map