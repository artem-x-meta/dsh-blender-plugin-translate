import fs from 'node:fs';
import path from 'node:path';
import { CFG } from '../config.js';
import { errorMessage } from '../core/json.js';
import { holderResponsive, killHolders } from '../ports.js';
// Never able to get a slot, and the watchdog respawns an instance every 15 s that hits EADDRINUSE and exits ⇒ infinite loop; the only way out is a manual kill -9.
// Two layers of fallback: ① signal handling can no longer be "swallowed" (forced-exit timer); ② on EADDRINUSE, first decide whether the holder is alive or dead,
// a dead one gets SIGKILL, the port is reclaimed and listen is retried (no manual step, no watchdog needed).
const sleepMs = (ms) => new Promise((r) => setTimeout(r, ms));
export function startServer({ server, engine, port, host, routes }) {
    const onListening = () => console.log('[blender-rt] http://' + host + ':' + String(port) + '/  (routes: ' + routes.join(' ') + ')');
    let reclaimTries = 0;
    server.on('error', async (e) => {
        const code = e && e.code;
        if (code === 'EADDRINUSE' && reclaimTries < 2) {
            reclaimTries += 1;
            if (await holderResponsive(port)) {
                console.error('[dsh-blender-backend] port ' +
                    String(port) +
                    ' is held by a backend that **responds** — not reclaiming, exiting this run (leave it to the watchdog/op=start).');
                process.exit(0);
            }
            const k1 = killHolders(port, 'SIGTERM');
            await sleepMs(600);
            const k2 = killHolders(port, 'SIGKILL');
            console.error('[dsh-blender-backend] a wedged backend holds ' +
                String(port) +
                ': SIGTERM=[' +
                k1.join(',') +
                '] SIGKILL=[' +
                k2.join(',') +
                '] → retrying listen.');
            await sleepMs(300);
            try {
                server.listen(port, host, onListening);
                return;
            }
            catch (e2) {
                /* fall through to the generic error below */
            }
        }
        const msg = code === 'EADDRINUSE'
            ? 'Port ' +
                port +
                ' is already in use (EADDRINUSE) and automatic reclaim failed: most likely the previous backend is wedged. ' +
                'Fix: blender_viewport op=restart, or kill -9 the process whose cmdline in /proc contains "server.js --port ' +
                String(port) +
                '".'
            : 'listen failed: ' + errorMessage(e);
        console.error('[dsh-blender-backend] ' + msg);
        try {
            fs.writeFileSync(path.join(CFG.workDirWsl, 'backend-listen-error.txt'), msg, 'utf8');
        }
        catch (e2) {
            /* give up if even workDir cannot be written */
        }
        process.exit(1);
    });
    server.listen(port, host, onListening);
    const shutdown = () => {
        try {
            engine.stop();
        }
        catch (e) {
            /* ignore */
        }
        try {
            server.close();
        }
        catch (e) {
            /* ignore */
        }
        setTimeout(() => process.exit(0), 400);
    };
    process.on('SIGINT', shutdown);
    process.on('SIGTERM', shutdown);
}
//# sourceMappingURL=lifecycle.js.map
