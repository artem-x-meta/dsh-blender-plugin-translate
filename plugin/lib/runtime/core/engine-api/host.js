// engine API: host integration data source / start / stop (split out of server-compat.ts)
import { extractTag } from '../output/index.js';
import { KERNEL_BOOTSTRAP } from '../kernel/index.js';
export function createHostApi(E) {
    const { addon, clearWorkerReaper, ensureView, killWorkers } = E;
    return {
        async hostSceneItems(spec = {}) {
            await ensureView();
            const body = 'print("HOSTITEMS " + K.dsh_view_api["host_scene_items"](' +
                JSON.stringify(JSON.stringify(spec)) +
                '))';
            const info = extractTag(await addon.send('execute_code', { code: KERNEL_BOOTSTRAP + '\n' + body }, 60000, {
                noMark: true,
            }), 'HOSTITEMS');
            if (!info || info.ok === false)
                throw new Error('scene-items failed: ' + JSON.stringify(info).slice(0, 300));
            return info;
        },
        /**
         * Connect to the resident socket at startup.
         *
         * Fix (serial tax): the first version also sent a "best effort" un-awaited `get_addon_info` here.
         * AddonClient requests are a **serial queue** (queue.then(run) in transport/probes.ts), so that
         * fire-and-forget probe sat at the head of the queue for up to its 3s timeout — the /status and /doctor
         * calls right behind it could only follow, forcing their budgets down to 3.5s/3s. That probe's result was
         * never used and the connection itself is established by ensure(); removing it means the serial queue no
         * longer pays a tax for the startup probe (it and lifecycle's failure diagnose keep to their own jobs, no overlap).
         */
        async start() {
            await addon.ensure();
            return true;
        },
        // v0.9.4: workers are multi-instance now — closing the backend must reap **all** instances (it used to kill only the singleton)
        stop() {
            clearWorkerReaper();
            addon.close();
            killWorkers();
        },
    };
}
//# sourceMappingURL=host.js.map