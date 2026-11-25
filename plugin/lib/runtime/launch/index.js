// Launch GUI Blender (assembly: resolve → agent/dry-run → spawn → wait for the port)
import path from 'node:path';
import fs from 'node:fs';
import { CFG, winToWsl, wslToWin } from '../config.js';
import { WIN_TMP, BLENDER_EXE } from '../paths.js';
import { probeTcp } from '../backend_probe.js';
import { readJsonSafe } from '../proc_env.js';
import { tryLaunchAgent } from './resolve.js';
import { buildLaunchPlan, spawnDetachedBlender } from './spawn.js';
import { waitForAddonPort } from './wait.js';
export { ADDON_NAME_HINTS, LAUNCH_BOOT_PY, addonNameHit } from './resolve.js';
function resolveLaunchContext(opts) {
    const started = Date.now();
    const addonPort = Math.max(1, Math.min(65535, Number(opts.addonPort || CFG.addonPort) || 9876));
    const waitMs = Math.max(2000, Math.min(600000, Number(opts.waitMs || process.env.DSH_BLENDER_LAUNCH_WAIT_MS) || 90000));
    const exe = String(opts.exe || BLENDER_EXE || '');
    const steps = [];
    const statusWsl = path.join(winToWsl(WIN_TMP), 'launch-status.json');
    const base = {
        exe: exe || null,
        addonPort: addonPort,
        waitMs: waitMs,
        statusFile: statusWsl,
        statusFileWin: wslToWin(statusWsl),
        configFrom: CFG.source ? CFG.source.blenderExe : null,
    };
    return { started, addonPort, waitMs, exe, steps, statusWsl, base };
}
/** ① Already listening → do nothing (idempotent: repeated agent calls do not pile up a second Blender) */
async function alreadyLaunchedResult(ctx) {
    if (!(await probeTcp('127.0.0.1', ctx.addonPort, 800)))
        return null;
    const boot0 = readJsonSafe(ctx.statusWsl);
    return Object.assign({}, ctx.base, {
        ok: true,
        already: true,
        launched: false,
        waitedMs: Date.now() - ctx.started,
        steps: ctx.steps,
        boot: boot0,
        hint: 'the addon is already listening on this host at ' +
            ctx.addonPort +
            ' — no launch needed (to restart, close that Blender first, or use force to start another one)',
    });
}
/** 1.5 Prefer the Windows-side launch agent: a native launch ⇒ 0 interop calls; the port wait is completed by this function */
async function agentLaunchResult(ctx, agentRes) {
    let up = !!agentRes.listening;
    while (!up && Date.now() - ctx.started < ctx.waitMs) {
        if (await probeTcp('127.0.0.1', ctx.addonPort, 700)) {
            up = true;
            break;
        }
        await new Promise((r) => setTimeout(r, 500));
    }
    const st = ctx.steps.concat([
        up
            ? 'addon port ' + ctx.addonPort + ' is listening (' + String(Date.now() - ctx.started) + 'ms)'
            : 'waited ' + String(ctx.waitMs) + 'ms, the port is still closed',
    ]);
    return Object.assign({}, agentRes, {
        ok: up,
        listening: up,
        already: up,
        launched: agentRes.launched !== false,
        waitedMs: Date.now() - ctx.started,
        steps: st,
        hint: up
            ? 'GUI Blender is up and the addon is Connected (port ' +
                ctx.addonPort +
                ') — rt_do / rt_see are usable now (launched by the Windows agent, 0 interop calls)'
            : 'the Windows agent dispatched the launch, but the addon port ' +
                ctx.addonPort +
                ' was not listening within ' +
                String(ctx.waitMs) +
                'ms; check ' +
                String(ctx.base.statusFileWin || '') +
                ' (Blender launch status)',
    });
}
function missingExeResult(ctx) {
    return Object.assign({}, ctx.base, {
        ok: false,
        launched: false,
        already: false,
        waitedMs: Date.now() - ctx.started,
        steps: ctx.steps,
        error: 'blender.exe not found',
        hint: 'set DSH_BLENDER_EXE or blenderExe in dsh-blender.config.json (see docs/configuration-reference.md)',
    });
}
function dryRunResult(ctx, plan) {
    return Object.assign({}, ctx.base, {
        ok: true,
        dryRun: true,
        launched: false,
        already: false,
        args: plan.args,
        bootScript: plan.sp.win,
        steps: ['dryRun: only reports the command that would be executed'],
        hint: 'drop dry_run to actually launch',
    });
}
function missingBlenderPathResult(ctx, exe) {
    return Object.assign({}, ctx.base, {
        ok: false,
        launched: false,
        already: false,
        waitedMs: Date.now() - ctx.started,
        steps: ctx.steps,
        error: 'blender.exe does not exist: ' + exe,
        hint: 'set DSH_BLENDER_EXE or blenderExe in dsh-blender.config.json (the current value comes from ' +
            String(ctx.base.configFrom) +
            ')',
    });
}
function spawnErrorText(spawnErr) {
    return String(spawnErr !== null && typeof spawnErr === 'object' && 'message' in spawnErr
        ? spawnErr.message
        : spawnErr);
}
async function runSpawnedBlender(ctx, plan, exe) {
    const { child, spawnErrRef } = spawnDetachedBlender(exe, plan.args, plan.childEnv);
    let spawnErr = spawnErrRef.value;
    const listening = spawnErr
        ? false
        : await waitForAddonPort(ctx.started, ctx.waitMs, ctx.addonPort);
    // spawn's asynchronous 'error' may only arrive during the wait
    if (!spawnErr)
        spawnErr = spawnErrRef.value;
    if (spawnErr) {
        return Object.assign({}, ctx.base, {
            ok: false,
            launched: false,
            already: false,
            waitedMs: Date.now() - ctx.started,
            steps: ctx.steps,
            pid: child ? child.pid : null,
            error: 'cannot start the Blender process (' + exe + '): ' + spawnErrorText(spawnErr),
            hint: 'the path may not exist / not be executable / not be a Windows executable. Point DSH_BLENDER_EXE at the real blender.exe (on WSL something like /mnt/d/.../blender.exe)',
        });
    }
    ctx.steps.push('spawned ' + exe + ' pid=' + String(child ? child.pid : null) + ' (detached, decoupled from the backend process)');
    const boot = readJsonSafe(ctx.statusWsl);
    if (listening)
        ctx.steps.push('addon port ' + ctx.addonPort + ' is listening (' + String(Date.now() - ctx.started) + 'ms)');
    return Object.assign({}, ctx.base, {
        ok: listening,
        launched: true,
        already: false,
        listening: listening,
        pid: child ? child.pid : null,
        waitedMs: Date.now() - ctx.started,
        steps: ctx.steps,
        boot: boot,
        bootScript: plan.sp.win,
        args: plan.args,
        hint: listening
            ? 'GUI Blender is up and the addon is Connected (port ' +
                ctx.addonPort +
                ') — rt_do / rt_see are usable now (for write operations remember to take a lease with blender_viewport op=lease)'
            : 'waited ' +
                String(ctx.waitMs) +
                'ms and the port is still closed: look at the boot verdict in statusFile (addon not scanned / not in GUI mode / the exe started but crashed)',
    });
}
export async function launchBlender(opts = {}) {
    const ctx = resolveLaunchContext(opts);
    const already = await alreadyLaunchedResult(ctx);
    if (already)
        return already;
    const agentRes = await tryLaunchAgent(opts, ctx.addonPort, ctx.steps, ctx.base);
    if (agentRes)
        return agentLaunchResult(ctx, agentRes);
    if (!ctx.exe)
        return missingExeResult(ctx);
    const plan = buildLaunchPlan(opts, ctx.statusWsl);
    if (opts.dryRun)
        return dryRunResult(ctx, plan);
    // Do the existence check that is possible first (WSL-visible paths such as /mnt/...; native Windows paths cannot be checked, so those are left to the asynchronous error below)
    if (ctx.exe.charAt(0) === '/' && !fs.existsSync(ctx.exe))
        return missingBlenderPathResult(ctx, ctx.exe);
    return runSpawnedBlender(ctx, plan, ctx.exe);
}
//# sourceMappingURL=index.js.map
