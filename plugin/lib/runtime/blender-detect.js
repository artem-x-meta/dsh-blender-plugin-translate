/**
 * blender.exe detection — a standalone module split out of config.ts (pure detection, does not import config.ts, no cycles).
 *
 * Why a file of its own: scripts/check-function-budget.mjs sets a 600-line budget for TS files, and config.ts
 * was already at 550+; Windows Steam detection (multiple drive roots + fault-tolerant libraryfolders.vdf parsing + the dependency-injection surface)
 * has to live somewhere else, otherwise the only way through is growing the debt allow-list.
 *
 * Priority (high → low, matching docs/configuration-reference.md §4):
 *   1) DSH_BLENDER_EXE environment variable → from='config'
 *   2) blenderExe in the config file         → from='config'
 *   3) auto-scan install locations           → from='auto:install' (official installer) / 'auto:steam' (Steam library)
 *   4) PATH (Windows where / Linux which) → from='auto:path'
 *   5) none of the above                     → { exe: null, from: 'not-found' }
 *
 * Field report (2026-11-04 report §3.1): when Windows only scanned %ProgramFiles%\Blender Foundation,
 * on a machine with Blender installed in D:\Program Files\Steam\steamapps\common\Blender the exe was always null
 * and the headless worker spawned null outright — so Windows has to cover Steam too.
 *
 * Dependency injection: the defaults are the production implementations (process.env / fs / execFileSync / os.homedir),
 * so the tests (tests/unit/js/blender-detect.test.ts) can replace the whole set and build a Steam layout under os.tmpdir()
 * without depending on real drive letters / the registry / the Steam client, and it runs on Linux CI too.
 */
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { execFileSync } from 'node:child_process';
import { readString } from './core/json.js';
/** Common relative locations of a Windows Steam install root (the segment after the drive letter) */
const STEAM_REL_DIRS = [
    ['Program Files', 'Steam'],
    ['Program Files (x86)', 'Steam'],
    ['Steam'],
    ['SteamLibrary'],
];
const STEAM_ENV_KEYS = ['ProgramFiles', 'ProgramFiles(x86)', 'ProgramW6432'];
// The install directory the Steam client records for itself in the registry (HKCU\Software\Valve\Steam\SteamPath) —
// with Steam on G:/H: or in a non-default directory this is the only thing that can chain to the vdf (for 32-bit installs also look at WOW6432Node).
const STEAM_REG_KEYS = ['HKCU\\Software\\Valve\\Steam', 'HKLM\\SOFTWARE\\WOW6432Node\\Valve\\Steam'];
const DRIVE_LETTERS = ['C', 'D', 'E', 'F', 'G', 'H'];
function normPath(p) {
    return String(p).replace(/\\/g, '/').replace(/\/+$/, '').toLowerCase();
}
/** Deduplicate while preserving order (on Windows the same root arrives twice, once from env and once from the drive letters) */
function pushUnique(out, p) {
    const k = normPath(p);
    if (!k)
        return;
    if (out.some((x) => normPath(x) === k))
        return;
    out.push(p);
}
function existsSafe(p) {
    try {
        return fs.existsSync(p);
    }
    catch (e) {
        return false;
    }
}
function listDirSafe(p) {
    try {
        return fs.readdirSync(p);
    }
    catch (e) {
        return [];
    }
}
function readTextSafe(p) {
    try {
        return fs.readFileSync(p, 'utf8');
    }
    catch (e) {
        return null;
    }
}
function execText(cmd, args) {
    // windowsHide: where.exe is console-subsystem, so a host without a console gets a freshly allocated one (issue #43; no-op off Windows)
    return execFileSync(cmd, args, {
        encoding: 'utf8',
        timeout: 5000,
        windowsHide: true,
        stdio: ['ignore', 'pipe', 'ignore'],
    });
}
function detectDeps(over) {
    const d = {
        env: process.env,
        isWin: process.platform === 'win32',
        isMac: process.platform === 'darwin',
        homedir: () => os.homedir(),
        exists: existsSafe,
        listDir: listDirSafe,
        readText: readTextSafe,
        exec: execText,
        fileCfg: {},
    };
    const o = over || {};
    if (o.env !== undefined)
        d.env = o.env;
    if (o.isWin !== undefined)
        d.isWin = o.isWin;
    if (o.isMac !== undefined)
        d.isMac = o.isMac;
    if (o.homedir !== undefined)
        d.homedir = o.homedir;
    if (o.exists !== undefined)
        d.exists = o.exists;
    if (o.listDir !== undefined)
        d.listDir = o.listDir;
    if (o.readText !== undefined)
        d.readText = o.readText;
    if (o.exec !== undefined)
        d.exec = o.exec;
    if (o.fileCfg !== undefined)
        d.fileCfg = o.fileCfg;
    return d;
}
/**
 * Read every "path" value out of libraryfolders.vdf (fault-tolerant: no full VDF parse, only this one kind of key).
 *
 * Only quoted path values count: empty values, bare "path" key lines and comment/garbage lines are skipped; VDF's \\ escape is restored to \.
 * An unreadable file (readText returns null) → empty array, and the caller still tries the default roots.
 */
function parseVdfPaths(text) {
    const out = [];
    if (!text)
        return out;
    const re = /"path"\s+"((?:[^"\\]|\\.)*)"/gi;
    let m = re.exec(text);
    while (m) {
        const p = m[1].replace(/\\(.)/g, '$1').trim();
        if (p)
            out.push(p);
        m = re.exec(text);
    }
    return out;
}
/** Read the Steam install root from HKCU/HKLM SteamPath; null when unreadable (not Windows / no registry). */
function steamPathFromRegistry(d) {
    if (!d.isWin)
        return null;
    for (const key of STEAM_REG_KEYS) {
        try {
            const out = d.exec('reg.exe', ['query', key, '/v', 'SteamPath']);
            const m = /SteamPath\s+REG_SZ\s+(.+)/i.exec(out);
            if (m && m[1].trim())
                return m[1].trim().replace(/[\\/]+$/, '');
        }
        catch (e) {
            /* if the registry cannot be read, keep trying the common roots */
        }
    }
    return null;
}
/** Library directories under one Steam root: the root itself + whatever libraryfolders.vdf lists (missing/corrupt vdf leaves only the root) */
function steamLibraries(d, root) {
    const libs = [];
    pushUnique(libs, root);
    for (const lib of parseVdfPaths(d.readText(path.join(root, 'steamapps', 'libraryfolders.vdf')))) {
        pushUnique(libs, lib);
    }
    return libs;
}
/**
 * Steam roots that exist: the registry SteamPath wins (covers G:/H: and non-default directories),
 * then Steam under %ProgramFiles%/%ProgramFiles(x86)%/%ProgramW6432% and the common C–H locations are added.
 */
function steamRoots(d) {
    const all = [];
    const regRoot = steamPathFromRegistry(d);
    if (regRoot)
        pushUnique(all, regRoot);
    for (const key of STEAM_ENV_KEYS) {
        const base = readString(d.env[key]);
        if (base)
            pushUnique(all, path.join(base, 'Steam'));
    }
    for (const drive of DRIVE_LETTERS) {
        for (const rel of STEAM_REL_DIRS) {
            pushUnique(all, path.join(drive + ':' + path.sep, ...rel));
        }
    }
    return all.filter((root) => d.exists(root));
}
/**
 * Windows candidates: the official installer (versioned directories) first, then each Steam root / library.
 * Paths use path.join (which is path.win32.join on Windows), and a drive root carries an explicit separator,
 * so path.win32.join('C:', …) does not become a drive-relative path.
 */
function winCandidates(d) {
    const out = [];
    const pf = readString(d.env.ProgramFiles) || 'C:\\Program Files';
    const foundation = path.join(pf, 'Blender Foundation');
    for (const dir of d.listDir(foundation)) {
        if (/^Blender/i.test(dir)) {
            out.push({ exe: path.join(foundation, dir, 'blender.exe'), from: 'auto:install' });
        }
    }
    out.push({ exe: path.join(foundation, 'Blender', 'blender.exe'), from: 'auto:install' });
    for (const root of steamRoots(d)) {
        for (const lib of steamLibraries(d, root)) {
            out.push({
                exe: path.join(lib, 'steamapps', 'common', 'Blender', 'blender.exe'),
                from: 'auto:steam',
            });
        }
    }
    return out;
}
/** macOS candidates: the .app bundle, executable under Contents/MacOS (behaviour identical to before the split) */
function macCandidates(d) {
    const out = [];
    const homes = ['/Applications', path.join(d.homedir(), 'Applications')];
    for (const v of d.listDir('/Volumes'))
        homes.push(path.join('/Volumes', v, 'Applications'));
    for (const base of homes) {
        for (const dir of d.listDir(base)) {
            if (/^Blender.*\.app$/i.test(dir)) {
                out.push({
                    exe: path.join(base, dir, 'Contents', 'MacOS', 'Blender'),
                    from: 'auto:install',
                });
            }
        }
        out.push({
            exe: path.join(base, 'Blender.app', 'Contents', 'MacOS', 'Blender'),
            from: 'auto:install',
        });
    }
    return out;
}
/** Linux/WSL candidates: the official install and Steam libraries under /mnt/<drive>/… (behaviour identical to before the split, from values stay auto:install too) */
function linuxCandidates(d) {
    const out = [];
    for (const drive of ['c', 'd', 'e', 'f']) {
        const base = '/mnt/' + drive;
        if (!d.exists(base))
            continue;
        const foundation = path.join(base, 'Program Files', 'Blender Foundation');
        for (const dir of d.listDir(foundation)) {
            if (/^Blender/i.test(dir)) {
                out.push({ exe: path.join(foundation, dir, 'blender.exe'), from: 'auto:install' });
            }
        }
        for (const rel of [
            'SteamLibrary/steamapps/common/Blender/blender.exe',
            'Steam/steamapps/common/Blender/blender.exe',
            'Program Files/Blender Foundation/Blender/blender.exe',
        ]) {
            out.push({ exe: path.join(base, rel), from: 'auto:install' });
        }
    }
    return out;
}
export function detectBlenderExe(over = {}) {
    const d = detectDeps(over);
    const given = readString(d.env.DSH_BLENDER_EXE) || readString(d.fileCfg.blenderExe);
    if (given)
        return { exe: given, from: 'config' };
    const cands = d.isWin ? winCandidates(d) : d.isMac ? macCandidates(d) : linuxCandidates(d);
    for (const c of cands) {
        if (d.exists(c.exe))
            return { exe: c.exe, from: c.from };
    }
    // PATH fallback (which on Linux, where on Windows)
    try {
        const out = d
            .exec(d.isWin ? 'where.exe' : 'which', ['blender'])
            .split(/\r?\n/)
            .filter(Boolean)[0];
        if (out)
            return { exe: out.trim(), from: 'auto:path' };
    }
    catch (e) {
        /* not installed on PATH */
    }
    return { exe: null, from: 'not-found' };
}
//# sourceMappingURL=blender-detect.js.map