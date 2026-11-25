import { readFileSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { errorMessage } from '../contracts/dynamic.js';
export const BUNDLED_SKILL_PROVIDER = 'dsh-blender-plugin';
export const BUNDLED_SKILL_RANK = 600;
export const BUNDLED_SKILL_DIR = fileURLToPath(new URL('../../skills/blender-modeling/', import.meta.url));
let bundledSkillCache;
let bundledSkillWarned = false;
/** Parse the YAML frontmatter of SKILL.md (only the name/description this plugin needs; no yaml dependency). */
export function parseSkillFrontmatter(raw) {
    const m = /^---\r?\n([\s\S]*?)\r?\n---(?:\r?\n|$)/.exec(raw);
    if (!m)
        return { meta: {}, body: raw };
    const meta = {};
    let key = '';
    for (const line of m[1].split(/\r?\n/)) {
        const kv = /^([A-Za-z0-9_-]+):\s*(.*)$/.exec(line);
        if (kv) {
            key = kv[1];
            let v = kv[2].trim();
            if ((v.startsWith('"') && v.endsWith('"')) || (v.startsWith("'") && v.endsWith("'")))
                v = v.slice(1, -1);
            meta[key] = v;
            continue;
        }
        // YAML folded / multi-line continuation: indented lines join the previous key
        if (key && /^\s+\S/.test(line))
            meta[key] = (meta[key] ? meta[key] + ' ' : '') + line.trim();
    }
    return { meta, body: raw.slice(m[0].length) };
}
export function readBundledSkill() {
    if (bundledSkillCache !== undefined)
        return bundledSkillCache;
    try {
        const raw = readFileSync(path.join(BUNDLED_SKILL_DIR, 'SKILL.md'), 'utf8');
        const { meta, body } = parseSkillFrontmatter(raw);
        const name = String(meta.name || '').trim();
        const description = String(meta.description || '').trim();
        if (!/^[a-z0-9]+(?:-[a-z0-9]+)*$/.test(name) || !description) {
            bundledSkillCache = null;
            return null;
        }
        bundledSkillCache = { name, description, content: body };
        return bundledSkillCache;
    }
    catch {
        bundledSkillCache = null;
        return null;
    }
}
export function createBundledSkillProvider() {
    const skill = readBundledSkill();
    if (!skill)
        return null;
    const skillFile = path.join(BUNDLED_SKILL_DIR, 'SKILL.md');
    const resourceBase = { kind: 'directory', path: BUNDLED_SKILL_DIR.split(path.sep).join('/') };
    const candidate = {
        name: skill.name,
        description: skill.description,
        invocation: { modelInvocable: true, userInvocable: true },
        source: 'bundled',
        provider: BUNDLED_SKILL_PROVIDER,
        rank: BUNDLED_SKILL_RANK,
        resourceBase,
        path: skillFile,
        locator: skillFile,
    };
    return {
        name: BUNDLED_SKILL_PROVIDER,
        // ⚠ this must be a Promise (async): the host registry's waitWithAbort calls `promise.then(...)`
        // directly on the return value when the caller passes a signal (every model-side lookup in dsh-skill/lib passes one) —
        // a synchronous return throws `promise.then is not a function`, the provider is silently skipped and the skill never actually loads.
        list: async () => [candidate],
        get: async () => ({
            name: skill.name,
            description: skill.description,
            invocation: { modelInvocable: true, userInvocable: true },
            source: 'bundled',
            provider: BUNDLED_SKILL_PROVIDER,
            resourceBase,
            path: skillFile,
            content: skill.content,
        }),
    };
}
function warn(ctx, message) {
    try {
        ctx.logger?.warn?.(message);
    }
    catch {
        /* a logging failure does not affect the tool surface */
    }
}
/**
 * Register the bundled skill in the host's skills registry (optional capability; failures only warn).
 * Use ctx.inject(['skills'], cb) to defer registration until the service is available: if the host has no skill
 * service, this child fiber just stays on standby and **never** prevents the plugin itself from starting.
 */
export function registerBundledSkill(ctx) {
    const provider = createBundledSkillProvider();
    if (provider === null) {
        if (!bundledSkillWarned) {
            bundledSkillWarned = true;
            warn(ctx, 'bundled skill not registered: skills/blender-modeling/SKILL.md is missing or its frontmatter is invalid (tool surface unaffected)');
        }
        return;
    }
    const mount = (c) => {
        try {
            c.skills?.registerProvider(() => provider);
        }
        catch (e) {
            warn(ctx, 'bundled skill registration failed: ' + errorMessage(e) + ' (tool surface unaffected)');
        }
    };
    try {
        if (typeof ctx.inject === 'function')
            ctx.inject(['skills'], (c) => mount(c));
        else if (ctx.skills && typeof ctx.skills.registerProvider === 'function')
            mount(ctx);
    }
    catch (e) {
        warn(ctx, 'bundled skill mount failed: ' + errorMessage(e) + ' (tool surface unaffected)');
    }
}
//# sourceMappingURL=skill.js.map
