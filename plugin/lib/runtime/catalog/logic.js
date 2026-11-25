// plan/command catalog logic (split out of catalog.ts, behaviour frozen)
import { createHash } from 'node:crypto';
import { execFileSync } from 'node:child_process';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { errorMessage } from '../core/json.js';
import { PLAN_CATALOG, planOpNames } from './data.js';
import { TOOL_DETAIL } from './tools.js';
import { COMMAND_CATALOG } from './commands.js';
function sha12(buf) {
    return createHash('sha256').update(buf).digest('hex').slice(0, 12);
}
const HERE = path.dirname(fileURLToPath(import.meta.url));
/**
 * Facade entry used by the clean-process import comparison: the build artifact lib/runtime/engine.js.
 * In the source layout (runtime/catalog.ts) it falls back to the in-package lib/runtime/engine.js; in the build layout it is the same directory.
 */
const RUNTIME_DIR = path.resolve(HERE, '..');
const ENGINE_SOURCE_PATH = (() => {
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
export function planEditDistance(a, b) {
    const m = a.length, n = b.length;
    let prev = new Array(n + 1);
    for (let j = 0; j <= n; j++)
        prev[j] = j;
    for (let i = 1; i <= m; i++) {
        const cur = [i];
        for (let j = 1; j <= n; j++) {
            cur[j] = Math.min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (a[i - 1] === b[j - 1] ? 0 : 1));
        }
        prev = cur;
    }
    return prev[n];
}
export function planOpSuggestion(opName) {
    const target = String(opName || '');
    if (!target)
        return null;
    let best = null;
    for (const name of planOpNames()) {
        const d = planEditDistance(target.toLowerCase(), name.toLowerCase());
        if (!best || d < best.d)
            best = { name: name, d: d };
    }
    if (!best || best.d > Math.max(3, Math.ceil(target.length * 0.34)))
        return null;
    const fam = PLAN_CATALOG.find((e) => e.prefix ? name0StartsWith(best.name, e.prefix) : e.ops.indexOf(best.name) >= 0);
    return {
        op: best.name,
        distance: best.d,
        family: fam ? fam.f : null,
        skeleton: fam ? fam.sk : null,
        when: fam ? fam.when : null,
    };
}
export function name0StartsWith(s, p) {
    return String(s).indexOf(p) === 0;
}
/** rt_cmd cross-channel correction: when a plan op is sent as an addon command, say straight away which tool it belongs to (this really happened in practice) */
export function planOpCrossChannelHint(addonName) {
    const n = String(addonName || '');
    if (!n || COMMAND_CATALOG[n])
        return null;
    // ① exact full-name hit (qc_render_catalog / audit_mesh / sculpt_apply …)
    for (const e of PLAN_CATALOG) {
        for (const op of e.ops) {
            const full = e.prefix ? e.prefix + op : op;
            if (n === full) {
                return ('"' +
                    n +
                    '" is an op of blender_rt_plan (' +
                    e.f +
                    ' family), not an addon command → ' +
                    'use blender_rt_plan(op="' +
                    full +
                    '", args={...}).' +
                    (e.sk ? ' Minimal skeleton: ' + e.sk : ''));
            }
        }
    }
    // ② only the second half was written (catalog / mesh / apply) → prepend the prefix
    for (const e of PLAN_CATALOG) {
        if (e.prefix && e.ops.indexOf(n) >= 0) {
            const full = e.prefix + n;
            return ('"' +
                n +
                '" is the ' +
                e.f +
                ' family op of the plan channel → the full form is blender_rt_plan(op="' +
                full +
                '").' +
                (e.sk ? ' Minimal skeleton: ' + e.sk : ''));
        }
    }
    // ③ neither → nearest neighbour
    const near = planOpSuggestion(n);
    if (near) {
        return ('"' +
            n +
            '" is neither an addon command nor a known plan op; the closest is "' +
            near.op +
            '" → ' +
            'blender_rt_plan(op="' +
            near.op +
            '").' +
            (near.skeleton ? ' Minimal skeleton: ' + near.skeleton : ''));
    }
    return null;
}
export function catalogFingerprint() {
    const parts = [];
    for (const e of PLAN_CATALOG)
        parts.push([e.f, e.prefix, e.ops.join(','), e.when, e.not, e.sk || '', e.key || ''].join('|'));
    return {
        catalogHash: sha12(Buffer.from(parts.join(String.fromCharCode(10)), 'utf8')),
        families: PLAN_CATALOG.length,
        opsCount: planOpNames().length,
        toolDetailKeys: Object.keys(TOOL_DETAIL).length,
        commandCatalogKeys: Object.keys(COMMAND_CATALOG).length,
    };
}
/** Start a separate clean node process that imports the **on-disk** engine.js facade — only it is the judge of "what the next request will get" */
export function probeDiskCatalog(timeoutMs) {
    if (!ENGINE_SOURCE_PATH)
        return { ok: false, error: 'engine source path unknown (cannot resolve from import.meta.url)' };
    const js = [
        'import(' + JSON.stringify(pathToFileURL(ENGINE_SOURCE_PATH).href) + ')',
        '.then(function (m) { process.stdout.write(JSON.stringify(Object.assign({ ok: true, pluginVersion: m.PLUGIN_VERSION }, m.catalogFingerprint()))); })',
        '.catch(function (e) { process.stdout.write(JSON.stringify({ ok: false, error: String((e && e.message) || e) })); })',
    ].join('');
    try {
        // ⚠ deliberately no "install dependencies" action beyond --input-type/-e: use the current node only, no network, no package installs.
        const out = execFileSync(process.execPath, ['-e', js], {
            encoding: 'utf8',
            timeout: Math.max(2000, Math.min(30000, Number(timeoutMs) || 8000)),
            stdio: ['ignore', 'pipe', 'pipe'],
            // issue #51: when the host runs inside Electron, process.execPath is the GUI executable; the probe child process must run in node mode.
            env: Object.assign({}, process.env, { DSH_PROVENANCE_PROBE: '1', ELECTRON_RUN_AS_NODE: '1' }),
            // windowsHide: node.exe is console-subsystem, so with no host console a new console gets allocated (issue #43; no-op off Windows)
            windowsHide: true,
        });
        const line = String(out).trim().split(String.fromCharCode(10)).filter(Boolean).pop() || '';
        return JSON.parse(line);
    }
    catch (e) {
        return { ok: false, error: errorMessage(e).slice(0, 200) };
    }
}
/**
 * Content-fingerprint comparison of the loaded version against the on-disk version.
 * By default it reads the disk once (~0.2 ms); only `verify:true` starts a clean process to compare (~120 ms), paying on demand.
 */
/** Short rendering of a single family (progressive disclosure: catalog first, then family, then *_help) */
export function renderFamilyText(e) {
    const L = [];
    L.push('family: ' + e.f + (e.prefix ? ' (prefix ' + e.prefix + ')' : ''));
    L.push('when to use: ' + e.when);
    L.push('when not to use: ' + e.not);
    L.push('ops: ' + e.ops.join(' / '));
    if (e.sk)
        L.push('minimal skeleton: ' + e.sk);
    if (e.key)
        L.push('key points: ' + e.key);
    L.push('quick reference: blender_rt_plan(op="' +
        (e.ops.indexOf('help') >= 0 ? (e.prefix ? e.prefix + 'help' : e.f + '_help') : 'help') +
        '")');
    return L.join(String.fromCharCode(10));
}
/**
 * The payload of op="catalog". By default it returns **short text only** (≈2–3k characters): for flash-class models,
 * reading "short enumeration + criteria + skeleton" is far more effective than 4.7k characters of prose; the structured detail is only
 * given for args={full:true} (that is for machines / post-mortems).
 *   op="catalog"                         → one page of catalog (family line + ops + skeleton key points)
 *   op="catalog", args={family:"sculpt"}  → expand only this family
 *   op="catalog", args={full:true}        → also include the structured families/tools
 */
/**
 * Single source of truth: the read-only op allowlist of the /plan channel (the only declaration site) (this file is the only declaration site).
 * server.mjs consumes it directly; tests/unit/js/contract/single-source.test.ts compares it name by name against the frozen baseline, to prevent migration from dropping or adding items.
 * Criterion: does not modify the scene, does not touch object transforms, does not register handlers. Adding a read-only op changes only this place.
 */
//# sourceMappingURL=logic.js.map
