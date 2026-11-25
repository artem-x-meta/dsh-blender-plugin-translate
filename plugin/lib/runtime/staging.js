/**
 * Headless script staging (moved out of engine.mjs) — so launch.mjs can use it too (this dependency was missed when launchBlender moved).
 *
 * Only cares about "can the Windows side see it"; writability of the backend's **own** status/ledger is handled separately by ensureWritableWorkDir on the server side.
 */
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { wslPathShared, wslToWin } from './config.js';
import { WIN_TMP, WSL_TMP, PY_ROOT, blenderJoin } from './paths.js';
import { errorMessage } from './core/json.js';
/**
 * Put a headless script somewhere **both sides can read** (with self-proving shareability since v0.9.6).
 *
 * Seen in the field: when workDir sits on a WSL-only mount (e.g. /tmp tmpfs), the Node side writes fine but Windows blender.exe
 * cannot open it → `OSError: Python file "\\wsl.localhost\Ubuntu\tmp\…\dsh_headless_*.py" could not be opened`,
 * the receipt has resultJson=null and this gets misread as "the lease/channel is broken". So this does not talk about "can we write" (Node always says yes),
 * only about **whether the Windows side can see it** (wslPathShared, reads the mount table), and prefers a shared directory.
 * Returns {wsl, win, staging}; staging goes into the receipt as is (if the directory was substituted it must be stated, never silently).
 */
/**
 * Headless script file name (issue: the old name went only to the millisecond → two concurrent runs in the same millisecond wrote the same .py,
 * one run's script overwritten by the other — the root of hard-to-diagnose symptoms like "what ran is not what I gave").
 * Uniqueness = milliseconds + an in-process monotonic counter (zero collisions within one process) + 4 random chars (cross-process collision guard).
 * Pure naming logic; tests/unit/js/headless-file-guard.test.ts runs a 5000-iteration collision test against it directly.
 */
let _nameSeq = 0;
export function headlessScriptName() {
    _nameSeq = (_nameSeq + 1) % 0x1000000;
    const rand = Math.random().toString(36).slice(2).padEnd(4, '0').slice(0, 4);
    return 'dsh_headless_' + Date.now().toString(36) + '_' + _nameSeq.toString(36) + rand + '.py';
}
export function writeHeadlessScript(code) {
    const name = headlessScriptName();
    const requested = WSL_TMP;
    const reqShared = wslPathShared(requested);
    // Candidates: the requested workDir (degraded when judged unshareable) → the user home (the distro root filesystem, visible to Windows) → the package tmp
    const wanted = { dir: requested, win: blenderJoin(WIN_TMP, name), label: 'workDir' };
    const homeTmp = {
        dir: path.join(os.homedir(), '.dsh', 'dsh-blender-rt'),
        win: null,
        label: 'fallback:home',
    };
    const pkgTmp = { dir: path.join(PY_ROOT, 'tmp'), win: null, label: 'fallback:pkg' };
    const cands = reqShared.shared === false ? [homeTmp, pkgTmp, wanted] : [wanted, homeTmp, pkgTmp];
    const errs = [];
    const tryWrite = (c) => {
        fs.mkdirSync(c.dir, { recursive: true });
        const wsl = path.join(c.dir, name);
        fs.writeFileSync(wsl, code, 'utf8');
        const sh = wslPathShared(c.dir);
        const substituted = path.resolve(c.dir) !== path.resolve(requested);
        return {
            wsl: wsl,
            win: c.win || wslToWin(wsl),
            staging: {
                requested: requested,
                requestedShared: reqShared.shared,
                requestedWhy: reqShared.why,
                used: c.dir,
                usedWin: c.win || wslToWin(wsl),
                usedShared: sh.shared,
                usedWhy: sh.why,
                label: c.label,
                substituted: substituted,
                note: substituted
                    ? 'workDir ' +
                        requested +
                        ' is not guaranteed visible on the Windows side (' +
                        reqShared.why +
                        ') → this run writes the script to ' +
                        c.dir +
                        ' (shared=' +
                        String(sh.shared) +
                        ', ' +
                        sh.why +
                        '); a headless script must live where Blender can read it'
                    : 'workDir shared-visibility check passed (' + sh.why + ')',
            },
        };
    };
    for (const c of cands) {
        if (wslPathShared(c.dir).shared === false) {
            errs.push(c.label + ' ' + c.dir + ': not guaranteed visible on the Windows side, skipping');
            continue;
        }
        try {
            return tryWrite(c);
        }
        catch (e) {
            errs.push(c.dir + ': ' + errorMessage(e));
        }
    }
    // Fallback: no shared candidate is writable → better to write into the (possibly unshared) workDir than to silently end up with no script
    for (const c of cands) {
        try {
            const r = tryWrite(c);
            r.staging.degraded = true;
            r.staging.note +=
                ' ⚠ this is the **degraded** path: every shared candidate failed to write, so the Windows-side Blender may not be able to read the script.';
            return r;
        }
        catch (e) {
            errs.push(c.dir + ': ' + errorMessage(e));
        }
    }
    throw new Error('cannot write headless script: ' + errs.join(' · '));
}
//# sourceMappingURL=staging.js.map