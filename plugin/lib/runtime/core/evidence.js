// Version/fingerprint self-proof, path audit, scene hygiene audit. ENGINE_SELF points at the runtime/engine.ts facade.
// @imports
import fs from 'node:fs';
import { IS_MAC, PKG_ROOT } from '../config.js';
import { createHash } from 'node:crypto';
import { catalogFingerprint, probeDiskCatalog } from '../catalog/index.js';
import { pyModuleFile, pyModuleNames } from '../paths.js';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { errorMessage, errorCode } from './json.js';
const RUNTIME_DIR = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
export const PLUGIN_VERSION = (() => {
    try {
        const pkg = JSON.parse(fs.readFileSync(path.join(PKG_ROOT, 'package.json'), 'utf8'));
        return typeof pkg.version === 'string' ? pkg.version : null;
    }
    catch (e) {
        return null;
    }
})();
function sha12(buf) {
    return createHash('sha256').update(buf).digest('hex').slice(0, 12);
}
/** Facade entry: candidates for the build layout lib/runtime/engine.js and for the in-package lib/runtime/engine.js under the source layout */
export const ENGINE_SOURCE_PATH = (() => {
    const built = path.join(RUNTIME_DIR, 'engine.js');
    const fromPkg = path.resolve(RUNTIME_DIR, '..', 'lib', 'runtime', 'engine.js');
    for (const c of [built, fromPkg]) {
        try {
            if (fs.existsSync(c))
                return c;
        }
        catch (e) {
            /* ignore */
        }
    }
    return built;
})();
const ENGINE_SELF = (() => {
    const info = {
        sourcePath: ENGINE_SOURCE_PATH,
        loadedAt: Date.now(),
        loadedAtText: '',
        loadedHash: null,
        loadedBytes: null,
        error: null,
    };
    info.loadedAtText = new Date(info.loadedAt).toISOString();
    try {
        const buf = fs.readFileSync(ENGINE_SOURCE_PATH);
        info.loadedHash = sha12(buf);
        info.loadedBytes = buf.length;
    }
    catch (e) {
        info.error = errorMessage(e).slice(0, 200);
    }
    return info;
})();
/**
 * By content hash (not size+mtime) — the cache key stays (size, mtime) to save IO, but **what is returned is the content fingerprint**.
 *
 * The key set keeps behaviour frozen: Python assets still use the old flat module name `<name>.py` as the key, but implementation files
 * are always resolved from the `runtime/py/modules.json` manifest (there are no flat shims now; generator / uv_tools
 * live in the geometry domain package), so they never drift with whether a shim happens to be in the directory.
 */
const _fpCache = new Map();
function runtimeFingerprint() {
    const out = {};
    const add = (p, key) => {
        const st = fs.statSync(p);
        const cacheKey = String(st.size) + ':' + String(Math.round(st.mtimeMs));
        let hit = _fpCache.get(p);
        if (!hit || hit.key !== cacheKey) {
            hit = { key: cacheKey, hash: sha12(fs.readFileSync(p)) };
            _fpCache.set(p, hit);
        }
        out[key] = hit.hash;
    };
    try {
        // Runtime files that are not Python (build artifacts lib/runtime/*.js, or the source tree runtime/*.ts).
        for (const f of fs.readdirSync(RUNTIME_DIR)) {
            if (!/\.(js|ts)$/.test(f) || /\.d\.ts$/.test(f))
                continue;
            add(path.join(RUNTIME_DIR, f), f);
        }
        // Python implementations: the single manifest runtime/py/modules.json; key names keep the old flat file names (<name>.py).
        for (const name of pyModuleNames())
            add(pyModuleFile(name), name + '.py');
    }
    catch (e) {
        /* ignore */
    }
    return out;
}
function pidAlive(pid) {
    const n = Number(pid);
    if (!Number.isFinite(n) || n <= 0)
        return false;
    try {
        process.kill(n, 0);
        return true;
    }
    catch (e) {
        return !!(errorCode(e) === 'EPERM');
    }
}
function pathAudit(stdout, stderr) {
    const warns = [];
    const text = String(stdout || '') + '\n' + String(stderr || '');
    const re = /Saved:\s*'([^']*)'/g;
    let m;
    // On macOS the host and Blender share one OS, so the "POSIX path rewritten by the Windows API into D:home…" class of problem cannot arise
    while (!IS_MAC && (m = re.exec(text)) !== null) {
        const p = m[1];
        if (/^[A-Za-z]:(home|mnt|tmp|var|usr|root|opt)/i.test(p)) {
            warns.push({
                code: 'posix_path_rewritten',
                evidence: p.slice(0, 200),
                hint: "Blender is a Windows process: '/home/…' is taken as «a relative path under the current drive root» → it really writes to C:\\home\\…." +
                    "In the script use K.win_path('/home/…') (or dsh_win_path) to turn it into a Windows-usable form before handing it to bpy.",
            });
        }
    }
    const re2 = /DSH_PATH_WARN (\{[^\n]*\})/g;
    while ((m = re2.exec(String(stdout || ''))) !== null) {
        try {
            const o = JSON.parse(m[1]);
            for (const w of o.warnings || [])
                warns.push(w);
        }
        catch (e) {
            /* ignore */
        }
    }
    // Deduplicate (the same path can be hit by Saved: several times)
    const seen = new Set();
    return warns.filter((w) => {
        const k = w.code + '|' + String(w.evidence || w.value || '');
        if (seen.has(k))
            return false;
        seen.add(k);
        return true;
    });
}
export function engineProvenance(opts) {
    const o = opts && typeof opts === 'object' ? opts : {};
    const cat = catalogFingerprint();
    const out = {
        sourcePath: ENGINE_SOURCE_PATH,
        pluginVersion: PLUGIN_VERSION,
        hashAlgo: 'sha256:12',
        loadedAt: ENGINE_SELF.loadedAtText,
        loadedHash: ENGINE_SELF.loadedHash,
        loadedBytes: ENGINE_SELF.loadedBytes,
        loadedReadError: ENGINE_SELF.error,
        currentHash: null,
        currentBytes: null,
        currentMtime: null,
        // Three-state: '' current = what is in the process is this copy on disk; stale = disk was changed and the backend must restart; unknown = unreadable/undecidable
        verdict: 'unknown',
        stale: null,
        staleReason: null,
        catalogHash: cat.catalogHash,
        families: cat.families,
        opsCount: cat.opsCount,
        toolDetailKeys: cat.toolDetailKeys,
        commandCatalogKeys: cat.commandCatalogKeys,
        // mtime is **for reference only** and takes no part in the verdict (which is exactly what was wrong with the old implementation)
        note: 'The verdict uses a content hash (sha256:12), not size/mtime; stale=true means the disk changed and this process is still the previous generation → restart the backend and ask again',
    };
    try {
        const buf = fs.readFileSync(ENGINE_SOURCE_PATH);
        const st = fs.statSync(ENGINE_SOURCE_PATH);
        out.currentHash = sha12(buf);
        out.currentBytes = buf.length;
        out.currentMtime = new Date(st.mtimeMs).toISOString();
    }
    catch (e) {
        out.staleReason = 'cannot read engine.mjs from disk: ' + errorMessage(e).slice(0, 160);
    }
    if (!ENGINE_SELF.loadedHash) {
        out.verdict = 'unknown';
        out.stale = null;
        out.staleReason =
            out.staleReason || 'the source was already unreadable at load time: ' + String(ENGINE_SELF.error || 'unknown');
    }
    else if (!out.currentHash) {
        out.verdict = 'unknown';
        out.stale = null;
    }
    else if (out.currentHash === ENGINE_SELF.loadedHash) {
        out.verdict = 'current';
        out.stale = false;
    }
    else {
        out.verdict = 'stale';
        out.stale = true;
        out.staleReason =
            'disk content changed (loaded ' +
                ENGINE_SELF.loadedHash +
                ' ≠ current ' +
                out.currentHash +
                ', loaded at ' +
                ENGINE_SELF.loadedAtText +
                ') → this process\'s catalog/routes are the previous generation: restart the backend and ask again, ' +
                'or run catalog args={verify:true} to cross-check from a clean process';
    }
    if (o.verify) {
        const disk = probeDiskCatalog(o.verifyTimeoutMs);
        out.diskCatalog = disk;
        if (disk && disk.ok) {
            const sameHash = disk.catalogHash === cat.catalogHash;
            out.diskVerdict = {
                ok: true,
                matchesLoadedCatalog: sameHash,
                families: disk.families,
                opsCount: disk.opsCount,
                catalogHash: disk.catalogHash,
                pluginVersion: disk.pluginVersion,
                note: sameHash
                    ? 'the catalog fingerprint a clean process reads from disk matches this process — the catalog is not stale'
                    : 'a clean process reading disk gets ' +
                        String(disk.families) +
                        ' family / ' +
                        String(disk.opsCount) +
                        ' op (' +
                        disk.catalogHash +
                        '), while this process answers ' +
                        String(cat.families) +
                        ' / ' +
                        String(cat.opsCount) +
                        ' (' +
                        cat.catalogHash +
                        ') → **this process\'s catalog is stale**; trust the clean process\'s copy (disk ' +
                        String(ENGINE_SOURCE_PATH) +
                        ')',
            };
        }
        else {
            out.diskVerdict = {
                ok: false,
                note: 'clean-process cross-check failed (does not affect this process\'s answer): ' + String((disk && disk.error) || 'unknown'),
            };
        }
    }
    return out;
}
/**
 * v2.6 (feedback #3 this round): multi-light hygiene — a **structured warning** for EEVEE shadow-pool overflow.
 *
 * In the field (thousands of lines spewed over 4 hours): 36 lights → the console prints on every frame
 *   Error: Shadow buffer full, may result in missing shadows and lower performance. (3040 / 2048)
 * while scene.eevee.shadow_pool_size = 4096 **silently has no effect** — it is an enum whose ceiling is 2048 (2 GB).
 * Old behaviour: the warning only flooded stderr and the model had to work it out itself; new behaviour: it goes into the receipt's warnings[] with a directly pasteable fix.
 */
export function sceneHygieneAudit(stdout, stderr) {
    const text = String(stdout || '') + String.fromCharCode(10) + String(stderr || '');
    const warns = [];
    const hits = text.match(/Shadow buffer full[^()]*\((\d+)\s*\/\s*(\d+)\)/g) || [];
    if (hits.length) {
        const last = hits[hits.length - 1].match(/\((\d+)\s*\/\s*(\d+)\)/);
        const FIX = [
            'import bpy',
            'bpy.context.scene.eevee.shadow_pool_size = "2048"   # the enum max is 2048; writing 4096 has no effect',
            'for o in bpy.data.objects:',
            '    if o.type == "LIGHT" and o.data.type in {"POINT", "SPOT"}:',
            '        o.data.use_shadow = False   # practical lights rarely need to cast shadows',
        ].join(String.fromCharCode(10));
        warns.push({
            code: 'eevee_shadow_pool_full',
            occurrences: hits.length,
            used_mb: last ? Number(last[1]) : null,
            limit_mb: last ? Number(last[2]) : null,
            hint: 'EEVEE shadow pool overflow (' +
                (last ? last[1] : '?') +
                '/' +
                (last ? last[2] : '?') +
                ' MB, occurred ' +
                hits.length +
                ' times): ' +
                'shadows go missing and renders get slower, but it **does not error out** — ignoring it gives you a render with "the shadows lost". ' +
                'How to fix: ① shadow_pool_size is an enum and its ceiling is 2048 (writing 4096 is silently ignored); ' +
                '② the main lever is fewer shadow casters: turn use_shadow off on all point/area lights and keep only the 2–4 that really need to cast; ' +
                '③ in big scenes lower shadow_resolution_scale as well.',
            fix: FIX,
            also: 'K.light_hygiene(apply=True) does all of it in one call (returns before/after counts)',
        });
    }
    return warns;
}
export { sha12, ENGINE_SELF, RUNTIME_DIR, runtimeFingerprint, pidAlive, pathAudit };
//# sourceMappingURL=evidence.js.map