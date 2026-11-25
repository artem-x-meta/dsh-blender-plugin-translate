import { engineProvenance } from '../evidence.js';
import { PLAN_CATALOG, PLAN_TOOL_MAP, TOOL_DETAIL, planOpNames, renderFamilyText, } from '../../catalog/index.js';
import { MODELING_CLASS_GUIDE, renderClassText, renderHandoff } from '../../classes.js';
/** Index lines for the default page (family / tool / expansion method) */
function catalogIndexLines() {
    const L = [];
    L.push('plan channel catalog: ' +
        PLAN_CATALOG.length +
        ' families / ' +
        planOpNames().length +
        ' ops. ' +
        'Pick a family by "what I want to do", then fill args from the "skeleton"; a misspelt parameter name reports "unknown parameter".');
    L.push('Look up by modeling class: args={classes:true} (' +
        MODELING_CLASS_GUIDE.length +
        ' classes) · args={class:"x"} single class · delegate to a subagent args={handoff:true}. ' +
        'Not covered (do not look for tools here): creature/organic modelling, cinematic lighting/volumes/compositing, character animation rigging.');
    L.push('');
    for (const e of PLAN_CATALOG) {
        L.push('· ' + e.f + (e.prefix ? ' (' + e.prefix + '*)' : '') + ': ' + e.when);
        L.push('    ops: ' + e.ops.join(' '));
        // The default page is a "one-page index": skeletons are capped at 90 chars (v2.6: families went 28→30, keeping the default catalog ≤9600 chars);
        // the full skeleton lives in args={family:…} and in the handoff block.
        if (e.sk)
            L.push('    skeleton: ' +
                (e.sk.length > 90 ? e.sk.slice(0, 90) + '… (full version in args={family:…})' : e.sk));
        // the not text carries a "'; **do not…**'" hard warning (the actionable clause) — the default page shows only that,
        // while the full not lives in args={family:…} and the handoff block; this keeps a one-page index short.
        const _not = String(e.not || '');
        const _wi = _not.indexOf('; **do not');
        L.push('    do not use: ' + (_wi >= 0 ? _not.slice(_wi + 1) : _not));
    }
    L.push('');
    L.push('Top-level tools (pick the tool first, then the op):');
    for (const t of PLAN_TOOL_MAP)
        L.push('  ' + t.t + ' — ' + t.use);
    L.push('');
    L.push('Expansion: op="catalog", args={family:"sculpt"} for one family; op="sculpt_help" etc. for operator detail; ' +
        'for structured detail aimed at machines/post-mortems use args={full:true}.');
    L.push('Tool parameter detail (the long-tail notes for heavy tools): args={tool:"rt_headless"}; queryable ' +
        Object.keys(TOOL_DETAIL).join(' / ') +
        '.');
    return L;
}
/** Catalog provenance lines (loaded/current/diskVerdict) */
function catalogProvenanceLines(prov) {
    const L = [];
    // v0.9.6: loaded-version provenance — one line gives the content fingerprint of "this copy in the process vs that copy on disk" (not mtime)
    if (prov.stale === true) {
        L.push('⚠ catalog provenance FAIL: engine.mjs on disk differs from the copy **this process loaded** (loaded ' +
            String(prov.loadedHash) +
            ' ≠ current ' +
            String(prov.currentHash) +
            ') → the catalog below is a **stale version**: ' +
            'restart the backend and ask again; to cross-check use op="catalog", args={verify:true} (spawns a clean process reading disk as the referee).');
    }
    else if (prov.diskVerdict &&
        prov.diskVerdict.ok === true &&
        prov.diskVerdict.matchesLoadedCatalog === false) {
        L.push('⚠ catalog provenance FAIL: a clean process reading disk sees ' +
            String(prov.diskVerdict.families) +
            ' families / ' +
            String(prov.diskVerdict.opsCount) +
            ' ops, while this process answers with ' +
            String(prov.families) +
            ' / ' +
            String(prov.opsCount) +
            ' → **this process catalog is stale** (restart the backend).');
    }
    else {
        L.push('catalog provenance: loaded engine.mjs ' +
            String(prov.loadedHash) +
            ' · disk ' +
            String(prov.currentHash) +
            ' · ' +
            (prov.verdict === 'current' ? 'match' : String(prov.verdict)));
    }
    return L;
}
function renderCatalogIndex(o, prov) {
    const L = catalogIndexLines().concat(catalogProvenanceLines(prov));
    const out = {
        ok: true,
        op: 'catalog',
        text: L.join(String.fromCharCode(10)),
        families: PLAN_CATALOG.map((e) => e.f),
        ops_count: planOpNames().length,
        provenance: prov,
    };
    if (o.full) {
        out.detail = PLAN_CATALOG.map((e) => ({
            family: e.f,
            prefix: e.prefix,
            ops: e.ops,
            when: e.when,
            not: e.not,
            skeleton: e.sk,
            key: e.key,
        }));
        out.tools = PLAN_TOOL_MAP;
    }
    return out;
}
export function catalogPayload(opts) {
    const o = opts && typeof opts === 'object' ? opts : {};
    // v0.9.6: loaded-version provenance — the catalog must also state "which generation this process loaded", so a disk mtime cannot impersonate the loaded version
    const prov = engineProvenance({
        verify: o.verify === true || o.verify === 'true',
        verifyTimeoutMs: o.verifyTimeoutMs,
    });
    // v0.9.6: tool parameter detail (the heavy-tool long tail) also goes through here — one entry point covers "which op / which family / which tool"
    if (o.tool) {
        const t = String(o.tool).replace(/^blender_/, '');
        const hit = TOOL_DETAIL[t];
        if (!hit)
            return {
                ok: false,
                error: 'no parameter detail for that tool: ' + o.tool,
                tools: Object.keys(TOOL_DETAIL),
                provenance: prov,
            };
        return { ok: true, op: 'catalog', tool: t, text: hit, provenance: prov };
    }
    if (o.family) {
        const e = PLAN_CATALOG.find((x) => x.f === String(o.family));
        if (!e)
            return {
                ok: false,
                error: 'unknown family: ' + o.family,
                families: PLAN_CATALOG.map((x) => x.f),
                provenance: prov,
            };
        return { ok: true, op: 'catalog', family: e.f, text: renderFamilyText(e), provenance: prov };
    }
    if (o.handoff) {
        // subagent handoff block: the main model gets it with one command and pastes it into the subagent prompt
        return { ok: true, op: 'catalog', handoff: true, text: renderHandoff(), provenance: prov };
    }
    if (o.classes) {
        const rows = MODELING_CLASS_GUIDE.map((r) => renderClassText(r)).join(String.fromCharCode(10) + String.fromCharCode(10));
        return {
            ok: true,
            op: 'catalog',
            classes: MODELING_CLASS_GUIDE.length,
            text: rows,
            provenance: prov,
        };
    }
    if (o.class) {
        const q = String(o.class).toLowerCase();
        const hit = MODELING_CLASS_GUIDE.find((r) => r.c === q) ||
            MODELING_CLASS_GUIDE.find((r) => (r.c + ' ' + r.name).toLowerCase().includes(q));
        if (!hit)
            return {
                ok: false,
                error: 'unknown modeling class: ' + o.class,
                classes: MODELING_CLASS_GUIDE.map((r) => r.c),
                provenance: prov,
            };
        return { ok: true, op: 'catalog', class: hit.c, text: renderClassText(hit), provenance: prov };
    }
    return renderCatalogIndex(o, prov);
}
//# sourceMappingURL=render.js.map