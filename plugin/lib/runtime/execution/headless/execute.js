import { finished } from 'node:stream/promises';
import { IS_MAC, IS_WIN } from '../../config.js';
import { BLENDER_EXE } from '../../paths.js';
import { spawnHeadless } from './process.js';
/** End both log streams and wait until their handles are released, so callers can delete the run directory safely. */
export async function closeHeadlessLogStreams(streams) {
    await closeLogStream(streams.soStream);
    await closeLogStream(streams.seStream);
}
/** End a log stream and wait until its handle is released. */
async function closeLogStream(stream) {
    if (!stream)
        return;
    const closed = finished(stream).catch(() => {
        /* the run result already carries the failure detail */
    });
    stream.end();
    await closed;
}
/** Spawn Blender, close the log streams, and turn a spawn-level failure into the public error. */
export async function executeHeadless(input) {
    const { p, built, childEnv, runRec, logStreams, t0 } = input;
    const res = await spawnHeadless(built.args, childEnv, p.timeoutMs, runRec, logStreams);
    const logsClosed = closeHeadlessLogStreams(logStreams);
    const ms = Date.now() - t0;
    if (res.spawnErr) {
        await logsClosed;
        const msg = 'cannot start the Blender process (' +
            BLENDER_EXE +
            '): ' +
            String((res.spawnErr && res.spawnErr.message) || res.spawnErr);
        const hint = 'auto-detection found no blender executable. Three ways to configure it (pick any one): ' +
            '① environment variable DSH_BLENDER_EXE=' +
            (IS_WIN
                ? 'D:\\...\\blender.exe'
                : IS_MAC
                    ? '/Applications/Blender.app/Contents/MacOS/Blender'
                    : '/mnt/d/.../blender.exe') +
            ' ② dsh-blender.config.json at the package root: {"blenderExe":"..."}' +
            ' ③ ~/.dsh/dsh-blender.config.json. For the current detection result see the config field of blender_viewport op=doctor.';
        throw Object.assign(new Error(msg), { code: 'blender_exe_missing', hint: hint });
    }
    return { res, stdout: String(res.so || ''), stderr: String(res.se || ''), ms, logsClosed };
}
//# sourceMappingURL=execute.js.map
