/**
 * Shared-build configuration resolution — **no source edits needed when changing machines**: environment variables → config file → auto-detection → defaults.
 *
 * This file is the only source of difference between the local build (the author's machine) and the shared build:
 *   the local build hard-codes workDir / blender.exe / ports in engine.mjs; the shared build takes everything from here.
 *
 * Priority (high → low):
 *   1) environment variables     DSH_BLENDER_* (see docs/configuration-reference.md)
 *   2) config file     $DSH_BLENDER_CONFIG → <package root>/dsh-blender.config.json → ~/.dsh/dsh-blender.config.json
 *   3) auto-detection     working directory (Windows user temp area) / Blender install path / PATH
 *   4) built-in defaults     addon 127.0.0.1:9876 · backend 127.0.0.1:9877 · lease TTL 600000 ms
 */
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { execFileSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import { isRecord, readString } from './core/json.js';
import { errorMessage } from './core/json.js';
import { detectBlenderExe } from './blender-detect.js';
const HERE = path.dirname(fileURLToPath(import.meta.url));
/**
 * Package root — there are two layouts, source and build, and both must be able to find package.json / dsh-blender.config.json:
 * - source layout: <pkg>/runtime/config.ts → one level up from HERE is the package root
 * - build layout: <pkg>/lib/runtime/config.js → two levels up is the package root (lib/ sits in between)
 */
export const PKG_ROOT = (() => {
    if (fs.existsSync(path.join(HERE, 'package.json')))
        return HERE;
    const parent = path.join(HERE, '..');
    if (fs.existsSync(path.join(parent, 'package.json')))
        return parent;
    return path.resolve(HERE, '..', '..');
})();
export const IS_WIN = process.platform === 'win32';
/** macOS: host and Blender are on the same machine and OS, so there is none of the Windows/WSL cross-OS path trouble */
export const IS_MAC = process.platform === 'darwin';
/**
 * Whether this really runs inside WSL (rather than native Linux) — issue #11.
 *
 * Why it has to be decided separately: `wslToWin()` used to distinguish only Windows / macOS, **treating everything else as "Linux host ⇒ WSL +
 * Blender on Windows"**, mapping the host absolute path to `\\wsl.localhost\<distro>\…`. On native Linux Blender
 * is on the same machine and OS as the host (the same shape as macOS); that mapping makes Blender read the string as a **relative path**, the output lands in a literal
 * backslash directory, and when the backend then reads the same path it hits ENOENT ⇒ `blender_rt_see` always reports `frame http 502`.
 *
 * Criterion: the environment variable wins (an interactive WSL always has one); then fall back to /proc/version — when dsh runs inside a systemd service it **does not inherit**
 * `WSL_DISTRO_NAME` (issue #6, seen in the field), yet that machine really is WSL, so it must not be misjudged as native Linux.
 * It is kept a pure function so the criterion can be compared on **any platform** (tests/unit/js/platform-paths.test.ts [1]).
 */
export function detectWsl(platform, env, procVersion) {
    if (platform === 'win32' || platform === 'darwin')
        return false;
    const e = env || {};
    if (e.WSL_DISTRO_NAME || e.WSL_INTEROP)
        return true;
    return /microsoft|wsl/i.test(String(procVersion || ''));
}
export const IS_WSL = detectWsl(process.platform, process.env, (function () {
    try {
        return fs.readFileSync('/proc/version', 'utf8');
    }
    catch (e) {
        return '';
    }
})());
/** WSL distro name (used to build the UNC path); on non-WSL platforms only for diagnostic display, see linuxDistroName() */
export const DISTRO = process.env.WSL_DISTRO_NAME || 'Ubuntu';
/** Native Linux distro name (feeds only the /doctor display field; WSL uses DISTRO) */
export function linuxDistroName() {
    try {
        const t = fs.readFileSync('/etc/os-release', 'utf8');
        const m = t.match(/^PRETTY_NAME="?([^"\n]+)"?/m) || t.match(/^NAME="?([^"\n]+)"?/m);
        if (m)
            return m[1].trim();
    }
    catch (e) {
        /* fall back to the platform name when it cannot be read, do not invent one */
    }
    return 'linux';
}
export const CONFIG_FILES = [
    process.env.DSH_BLENDER_CONFIG,
    path.join(PKG_ROOT, 'dsh-blender.config.json'),
    path.join(os.homedir(), '.dsh', 'dsh-blender.config.json'),
].filter((p) => Boolean(p));
function readJson(p) {
    try {
        return JSON.parse(fs.readFileSync(p, 'utf8'));
    }
    catch (e) {
        return null;
    }
}
function loadFileConfig() {
    for (const p of CONFIG_FILES) {
        const j = readJson(p);
        if (isRecord(j))
            return { cfg: j, from: p };
    }
    return { cfg: {}, from: null };
}
const FILE = loadFileConfig();
/** Windows path → WSL path (D:\a\b → /mnt/d/a/b; UNC → /…; returned as is on Windows) */
export function winToWsl(p) {
    const s = String(p || '');
    if (IS_WIN || IS_MAC)
        return s;
    const m = s.match(/^([A-Za-z]):[\\/](.*)$/);
    if (m)
        return '/mnt/' + m[1].toLowerCase() + '/' + m[2].replace(/\\/g, '/');
    // v0.9.3: UNC form (\\wsl.localhost\<distro>\home\… or \\wsl$\…) → /home/… as WSL sees it
    // The old version **returned it as is** → as soon as workDir was a WSL path (wslToWin converted it to UNC first), the ledger / results / trajectory
    // all ended up on a UNC string Node could not open (measured in practice: the stale reconciliation could not find the ledger).
    const u = s.match(/^\\\\wsl(?:\.localhost)?\\[^\\]+\\(.*)$/i);
    if (u)
        return '/' + u[1].replace(/\\/g, '/');
    return s;
}
/**
 * Host path → a path usable on the Blender process side.
 *   Windows      → backslashised (as is)
 *   WSL          → /mnt/x/... → X:\...; inside WSL → \\wsl.localhost\<distro>\...
 *   native Linux → **identity** (host and Blender share the machine and OS; like macOS it must not be rewritten across OSes) — issue #11
 *   macOS        → identity
 */
export function wslToWin(p) {
    const s = String(p || '');
    if (IS_MAC)
        return s;
    if (IS_WIN)
        return s.replace(/\//g, '\\');
    // Native Linux (not WSL): identity. Mapped to \\wsl.localhost\… the same-machine Blender would read it as a **relative path**,
    // and the output would land in a literal backslash directory (the frame PNG gets written but cannot be read ⇒ frame http 502, headless scripts will not open).
    if (!IS_WSL)
        return s;
    const m = s.match(/^\/mnt\/([a-z])\/(.*)$/i);
    if (m)
        return m[1].toUpperCase() + ':' + '\\' + m[2].replace(/\//g, '\\');
    if (s.startsWith('/'))
        return '\\\\wsl.localhost\\' + DISTRO + s.replace(/\//g, '\\');
    return s;
}
let _mountEntries;
function mountEntries() {
    if (_mountEntries !== undefined)
        return _mountEntries;
    _mountEntries = [];
    try {
        const oct = (s) => String(s).replace(/\\(040|011|012|134)/g, (m, o) => String.fromCharCode(parseInt(o, 8)));
        for (const line of fs.readFileSync('/proc/self/mounts', 'utf8').split('\n')) {
            const f = line.trim().split(' ');
            if (f.length < 3)
                continue;
            _mountEntries.push({ source: oct(f[0]), target: oct(f[1]), fstype: oct(f[2]) });
        }
    }
    catch (e) {
        _mountEntries = [];
    }
    return _mountEntries;
}
export function wslPathShared(p) {
    const s = String(p || '');
    if (IS_WIN)
        return { shared: true, why: 'windows' };
    if (s.charAt(0) !== '/')
        return { shared: null, why: 'not-absolute' };
    // native Linux: Blender runs on this same machine, so nothing can be invisible to it
    if (!IS_MAC && !IS_WSL)
        return { shared: true, why: 'native-linux-same-machine' };
    if (/^\/mnt\/[a-z](\/|$)/i.test(s))
        return { shared: true, why: 'drvfs-drive' };
    const ms = mountEntries();
    if (!ms.length)
        return { shared: null, why: 'no-mount-table' };
    const root = ms.find((m) => m.target === '/');
    let best = null;
    for (const m of ms) {
        const t = m.target === '/' ? '/' : m.target.replace(/\/+$/, '');
        const hit = t === '/' ? s.charAt(0) === '/' : s === t || s.indexOf(t + '/') === 0;
        if (hit && (!best || t.length > best.target.length))
            best = m;
    }
    if (!best)
        return { shared: null, why: 'no-mount-match' };
    if (root && best.source === root.source) {
        return {
            shared: true,
            why: 'distro-root-fs',
            source: best.source,
            fstype: best.fstype,
            mount: best.target,
        };
    }
    return {
        shared: false,
        why: 'separate-mount-not-guaranteed-windows-visible',
        source: best.source,
        fstype: best.fstype,
        mount: best.target,
    };
}
/** Ask Windows for %LOCALAPPDATA% from inside WSL (null when there is no interop) */
let _lad;
function winLocalAppData() {
    if (_lad !== undefined)
        return _lad;
    _lad = null;
    if (IS_WIN) {
        _lad = process.env.LOCALAPPDATA || null;
        return _lad;
    }
    if (IS_MAC)
        return null; // macOS has no %LOCALAPPDATA%; and does not need to call cmd.exe
    try {
        // The cwd must be a Windows-side directory: under a UNC path cmd.exe warns "UNC paths are not supported" and falls back to C:Windows
        const cwd = fs.existsSync('/mnt/c') ? '/mnt/c' : fs.existsSync('/mnt/d') ? '/mnt/d' : undefined;
        // windowsHide: avoid allocating a new console when spawning a Windows executable (cmd.exe, console subsystem) from the WSL side (issue #43)
        const out = execFileSync('cmd.exe', ['/c', 'echo', '%LOCALAPPDATA%'], {
            encoding: 'utf8',
            timeout: 5000,
            cwd: cwd,
            windowsHide: true,
        }).trim();
        if (/^[A-Za-z]:\\/.test(out))
            _lad = out;
    }
    catch (e) {
        /* no interop (pure Linux) → use os.tmpdir() */
    }
    return _lad;
}
function probeWritable(dir) {
    // Only a real write counts as writable (Node's mkdir succeeding does not mean writable: read-only mounts / permissions / over-long paths all blow up one step later)
    try {
        fs.mkdirSync(dir, { recursive: true });
        const p = path.join(dir, '.dsh_write_probe_' + process.pid);
        fs.writeFileSync(p, 'ok', 'utf8');
        fs.unlinkSync(p);
        return { ok: true };
    }
    catch (e) {
        return { ok: false, why: errorMessage(e).slice(0, 200) };
    }
}
function resolveWorkDirRaw() {
    const given = readString(process.env.DSH_BLENDER_WORKDIR) || readString(FILE.cfg.workDir);
    if (given) {
        const win = /^[A-Za-z]:[\\/]/.test(given) ? given : wslToWin(given);
        return { win: win, wsl: winToWsl(given), from: 'config' };
    }
    if (IS_MAC) {
        // macOS: a user-level persistent directory (not os.tmpdir(), which the system cleans out and frames/ledger would be lost)
        const d = path.join(os.homedir(), '.dsh-blender-rt');
        return { win: d, wsl: d, from: 'auto:homedir' };
    }
    const lad = winLocalAppData();
    if (lad) {
        const win = path.win32.join(lad, 'dsh-blender-rt');
        return { win: win, wsl: winToWsl(win), from: 'auto:localappdata' };
    }
    const t = path.join(os.tmpdir(), 'dsh-blender-rt');
    return { win: t, wsl: t, from: 'auto:tmpdir' };
}
/**
 * workDir **writability self-proof + fallback** (field case: after /mnt/d turned read-only the backend could not write its own status/ledger and would not start,
 * and the error only said "look at the backend log", with not one line saying "your workDir is not writable" — 40 minutes went like that).
 * Order: candidate from config/auto-detection → the package tmp (inside the workspace, usually writable) → OS tmpdir. A fallback must leave an explicit trace.
 */
function resolveWorkDir() {
    const cand = resolveWorkDirRaw();
    const pr = probeWritable(cand.wsl);
    if (pr.ok)
        return Object.assign({}, cand, { writable: true, fallback: null });
    const pkgTmp = path.join(PKG_ROOT, 'tmp');
    const tries = [
        { dir: pkgTmp, from: 'fallback:pkg-tmp' },
        { dir: path.join(os.tmpdir(), 'dsh-blender-rt'), from: 'fallback:tmpdir' },
    ];
    const errs = [cand.wsl + ' (' + cand.from + '): ' + pr.why];
    for (const t of tries) {
        const p2 = probeWritable(t.dir);
        if (p2.ok) {
            return {
                win: wslToWin(t.dir),
                wsl: t.dir,
                from: t.from,
                writable: true,
                fallback: {
                    requested: cand.wsl,
                    requestedFrom: cand.from,
                    why: pr.why,
                    used: t.dir,
                    usedFrom: t.from,
                    errs: errs,
                },
            };
        }
        errs.push(t.dir + ' (' + t.from + '): ' + p2.why);
    }
    // Nothing is writable: still return the original candidate (upper layers will error while writing), but carry the evidence along
    return Object.assign({}, cand, {
        writable: false,
        fallback: {
            requested: cand.wsl,
            requestedFrom: cand.from,
            why: pr.why,
            used: cand.wsl,
            usedFrom: 'none',
            errs: errs,
        },
    });
}
const WORK = resolveWorkDir();
/** blender.exe detection lives in runtime/blender-detect.ts (dependency injection friendly; Windows includes the Steam libraries).
 *  config.ts no longer re-exports detectBlenderExe: callers that need the detection result import blender-detect.js directly;
 *  it is used only once here (module-level CFG); for the detection source see CFG.source.blenderExe. */
const BLENDER = detectBlenderExe({ fileCfg: FILE.cfg });
function num(v, d) {
    const n = Number(v);
    return Number.isFinite(n) && n > 0 ? n : d;
}
/** Final config (computed once, module-level constant) */
export const CFG = {
    // channels
    addonHost: readString(process.env.DSH_BLENDER_ADDON_HOST) || readString(FILE.cfg.addonHost) || '127.0.0.1',
    addonPort: num(process.env.DSH_BLENDER_ADDON_PORT || readString(FILE.cfg.addonPort), 9876),
    httpPort: num(process.env.DSH_BLENDER_HTTP_PORT || readString(FILE.cfg.httpPort), 9877),
    /**
     * Windows-side launch proxy (default 127.0.0.1:9878).
     * WSL goes through it to bring up the GUI Blender ⇒ zero interop calls per launch, avoiding the relay idle leak of microsoft/WSL#41173
     * (an Interop thread eats a whole core and cannot be released).
     * When the proxy is offline it falls back to the old interop spawn automatically; set it to "off" to force that fallback.
     */
    launchAgentUrl: String(process.env.DSH_BLENDER_LAUNCH_AGENT_URL ||
        readString(FILE.cfg.launchAgentUrl) ||
        'http://127.0.0.1:9878').replace(/\/+$/, ''),
    holder: readString(process.env.DSH_BLENDER_HOLDER) ||
        readString(FILE.cfg.holder) ||
        'plugin-pid-' + String(process.pid),
    leaseTtlMs: num(process.env.DSH_BLENDER_LEASE_TTL_MS || readString(FILE.cfg.leaseTtlMs), 600000),
    // directories (paired: the Windows side writes for Blender, the host side reads for Node)
    workDirWin: WORK.win,
    workDirWsl: WORK.wsl,
    /** workDir probe-write result and fallback trace (null = the original candidate is writable; non-null = it fell back, see errs) */
    workDirFallback: WORK.fallback || null,
    workDirWritable: WORK.writable !== false,
    // headless process
    blenderExe: BLENDER.exe,
    /** The user's Blender config directory (where the GPU preference lives): a headless process cannot read it by default → to inherit it, set it (together with factory_startup=false) */
    blenderUserConfig: readString(process.env.DSH_BLENDER_USER_CONFIG) ||
        readString(process.env.BLENDER_USER_CONFIG) ||
        readString(FILE.cfg.blenderUserConfig) ||
        null,
    blenderUserScripts: readString(process.env.DSH_BLENDER_USER_SCRIPTS) ||
        readString(process.env.BLENDER_USER_SCRIPTS) ||
        readString(FILE.cfg.blenderUserScripts) ||
        null,
    /** Local port of the hot headless worker (kept distinct from addon 9876 / backend 9877) */
    workerPort: num(process.env.DSH_BLENDER_WORKER_PORT || readString(FILE.cfg.workerPort), 9879),
    // provenance (for doctor / logs / tutorial troubleshooting)
    source: { configFile: FILE.from, workDir: WORK.from, blenderExe: BLENDER.from },
};
/**
 * Paired paths: `...Win` is for the Blender process, `...Wsl` is for the host Node.
 * On macOS the two are the same shape, so path.win32.join must not be applied blindly any more — that would produce
 * \\Users\\...\\dsh_live_viewport.png, which Blender on the mac cannot open (frame capture fails silently).
 */
function blenderSidePath(p, name) {
    if (IS_MAC)
        return path.join(p, name);
    if (IS_WIN)
        return path.win32.join(p, name);
    return wslToWin(path.join(p, name));
}
export const PATHS = {
    livePngWin: blenderSidePath(CFG.workDirWin, 'dsh_live_viewport.png'),
    livePngWsl: path.join(CFG.workDirWsl, 'dsh_live_viewport.png'),
    viewPngWin: blenderSidePath(CFG.workDirWin, 'dsh_view_capture.png'),
    viewPngWsl: path.join(CFG.workDirWsl, 'dsh_view_capture.png'),
};
/** Config summary (printed for self-check / troubleshooting; blender_rt_headless also uses it to hint when the exe is missing)
 *  over.httpPort: the port the backend actually listens on (the --port command-line flag overrides the configured value, so the summary has to follow it) */
export function describeConfig(over = {}) {
    const o = over || {};
    return {
        platform: process.platform,
        // WSL reports the distro name (the very one used in the UNC path); native Linux reports its own distro — stop reporting Manjaro as 'Ubuntu' (issue #11)
        distro: IS_WIN || IS_MAC ? null : IS_WSL ? DISTRO : linuxDistroName(),
        addon: CFG.addonHost + ':' + String(CFG.addonPort),
        http: '127.0.0.1:' + String(o.httpPort || CFG.httpPort),
        workDir: {
            win: CFG.workDirWin,
            wsl: CFG.workDirWsl,
            from: CFG.source.workDir,
            fallback: CFG.workDirFallback,
            // v0.9.6: whether the Windows side can see this working directory (false = headless scripts will fail to open, the directory has to be changed)
            shared: wslPathShared(CFG.workDirWsl),
        },
        blenderExe: CFG.blenderExe,
        blenderFrom: CFG.source.blenderExe,
        blenderUserConfig: CFG.blenderUserConfig,
        blenderUserScripts: CFG.blenderUserScripts,
        workerPort: CFG.workerPort,
        configFile: CFG.source.configFile,
        holder: CFG.holder,
        leaseTtlMs: CFG.leaseTtlMs,
        env: {
            DSH_BLENDER_WORKDIR: process.env.DSH_BLENDER_WORKDIR || null,
            DSH_BLENDER_EXE: process.env.DSH_BLENDER_EXE || null,
            DSH_BLENDER_HTTP_PORT: process.env.DSH_BLENDER_HTTP_PORT || null,
            DSH_BLENDER_ADDON_PROTOCOL: process.env.DSH_BLENDER_ADDON_PROTOCOL || null,
            DSH_BLENDER_CONFIG: process.env.DSH_BLENDER_CONFIG || null,
        },
    };
}
//# sourceMappingURL=config.js.map