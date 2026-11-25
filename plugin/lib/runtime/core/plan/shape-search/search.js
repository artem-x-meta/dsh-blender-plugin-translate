// shape-search Python script generation and inner-loop driving (split out of shape-search.ts, behaviour frozen)
import { errorMessage } from '../../json.js';
import { pyIndent, pyLit } from './axes.js';
/** Two-stage dedent: ① dedent the whole body by the first line's indent; ② dedent the continuation lines by their common indent once more (nested blocks keep their relative depth). */
function normalizeBody(src) {
    const lines = String(src).replace(/\t/g, '    ').split('\n');
    const ind = (l) => l.match(/^ */)[0].length;
    const firstIdx = lines.findIndex((l) => l.trim());
    if (firstIdx < 0)
        return lines.join('\n');
    const i0 = ind(lines[firstIdx]);
    let out = i0 > 0
        ? lines.map((l, k) => k === firstIdx || !l.trim()
            ? k === firstIdx
                ? l.slice(i0)
                : l
            : l.slice(Math.min(i0, ind(l))))
        : lines.slice();
    const tail = out.slice(firstIdx + 1).filter((l) => l.trim());
    const iTail = tail.length ? Math.min(...tail.map(ind)) : 0;
    if (iTail > 0)
        out = out.map((l, k) => (k > firstIdx && l.trim() ? l.slice(iTail) : l));
    return out.join('\n');
}
export function buildSetupSrc(p, applyBody) {
    const parts = ['import bpy', 'import math', 'import random'];
    if (p.setup)
        parts.push(normalizeBody(p.setup));
    parts.push(applyBody
        ? 'def apply(p):\n' + pyIndent(normalizeBody(applyBody), '    ')
        : 'def apply(p):\n    pass');
    return parts.join('\n') + '\n';
}
export function buildStepSrc(strategy, axes, combos) {
    if (strategy === 'grid') {
        const axesLit = '[' + axes.map((a) => '[' + JSON.stringify(a.k) + ', ' + pyLit(a.vals) + ']').join(', ') + ']';
        return ('_axes = ' +
            axesLit +
            '\n_i = ns["i"] % ' +
            String(combos) +
            '\n_p = {}\n' +
            'for _k, _vs in _axes:\n    _p[_k] = _vs[_i % len(_vs)]\n    _i //= len(_vs)\n' +
            'ns["params"] = _p\n');
    }
    const lines = axes.map((a) => {
        if (a.spec.kind === 'enum')
            return '    ' + JSON.stringify(a.k) + ': random.choice(' + pyLit(a.vals) + ')';
        if (a.spec.integer)
            return ('    ' +
                JSON.stringify(a.k) +
                ': int(round(random.uniform(' +
                String(a.spec.min) +
                ', ' +
                String(a.spec.max) +
                ')))');
        return ('    ' +
            JSON.stringify(a.k) +
            ': random.uniform(' +
            String(a.spec.min) +
            ', ' +
            String(a.spec.max) +
            ')');
    });
    return 'ns["params"] = {\n' + lines.join(',\n') + '\n}\n';
}
export function buildMeasureSrc(applyBody, measure, objective, target, targetSize, views, ref, refBox, bins) {
    if (measure)
        return (applyBody ? 'apply(ns["params"])\n' : '') + String(measure) + '\n';
    const lines = [];
    if (applyBody)
        lines.push('apply(ns["params"])');
    if (objective === 'aabb_err') {
        lines.push('ns["score"] = K.dsh_measure["aabb_err"](' +
            JSON.stringify(target) +
            ', ' +
            pyLit(targetSize) +
            ')');
    }
    else {
        const fn = objective === 'profile_err' ? 'profile_err' : 'silhouette_iou';
        const extra = fn === 'profile_err' ? ', ' + String(bins) : '';
        const call = (viewLit) => 'K.dsh_measure[' +
            JSON.stringify(fn) +
            '](' +
            viewLit +
            ', ' +
            JSON.stringify(ref) +
            ', ' +
            pyLit(refBox) +
            extra +
            ')';
        if (views.length === 1) {
            lines.push('ns["score"] = ' + call(pyLit(views[0])));
        }
        else {
            lines.push('_vs = ' + pyLit(views));
            lines.push('_ss = [' + call('_v') + ' for _v in _vs]');
            lines.push('ns["score"] = sum(_ss) / float(len(_ss))');
            lines.push('ns["metrics"] = {"per_view": _ss}');
        }
    }
    return lines.join('\n') + '\n';
}
export function buildSpec(setupSrc, stepSrc, measureSrc, iterations, limits) {
    const { budgetMs, interval, measureEvery, minimize, topK, patience } = limits;
    return {
        setup: setupSrc,
        step: stepSrc,
        measure: measureSrc,
        iterations: iterations,
        budget_ms: budgetMs,
        interval: interval,
        measure_every: measureEvery,
        minimize: minimize,
        top_k: topK,
        patience: patience,
        redraw_every: 0,
    };
}
export function buildSpecEcho(objective, strategy, combos, iterations, limits, norm, targets, p) {
    const { budgetMs, topK, patience, minimize } = limits;
    const { views, ref, target } = targets;
    return {
        objective: objective,
        strategy: strategy,
        combos: combos,
        iterations: iterations,
        budget_ms: budgetMs,
        minimize: minimize,
        top_k: topK,
        patience: patience,
        param_names: Object.keys(norm),
        views: views.length,
        ref: ref || null,
        target: target || null,
        restore: String(p.restore || 'best'),
    };
}
export async function preloadForSearch(E, renderObjective) {
    try {
        await E.ensureRunner();
        if (renderObjective) {
            await E.ensureQc();
            await E.ensureView();
        }
        return null;
    }
    catch (e) {
        return {
            ok: false,
            op: 'shape_search',
            stage: 'preload',
            error: 'Failed to inject runner/qc/view: ' + errorMessage(e).slice(0, 240),
            hint: 'Is GUI Blender connected? This op only works in a GUI session (bpy.app.timers does not fire headless)',
        };
    }
}
export async function startSearchLoop(E, spec, specEcho) {
    let started;
    try {
        started = (await E.loopStart(spec));
    }
    catch (e) {
        return {
            ok: false,
            op: 'shape_search',
            stage: 'start',
            error: errorMessage(e).slice(0, 300),
            spec_echo: specEcho,
        };
    }
    if (!started || started.ok === false) {
        return {
            ok: false,
            op: 'shape_search',
            stage: 'start',
            spec_echo: specEcho,
            error: (started && (started.err || started.error)) || 'Inner loop failed to start',
            detail: started || null,
            hint: 'If it reports loop already running: run blender_rt_loop(op="status") to inspect the previous round, and op="stop" if needed',
        };
    }
    return null;
}
export async function pollSearchLoop(E, waitCap) {
    const t0 = Date.now();
    let st = null, timedOut = false, pollError = null;
    try {
        st = await E.loopStatus(8);
        while (st && st.running === true) {
            if (Date.now() - t0 > waitCap) {
                timedOut = true;
                await E.loopStop();
                await new Promise((r) => setTimeout(r, 300));
                st = await E.loopStatus(8);
                break;
            }
            await new Promise((r) => setTimeout(r, 300));
            st = await E.loopStatus(8);
        }
    }
    catch (e) {
        pollError = errorMessage(e).slice(0, 300);
    }
    return { st, timedOut, pollError };
}
export async function fetchBoardAndExport(E, p, topK, objective) {
    let board;
    let exported = null;
    try {
        board = (await E.loopBoard(topK > 0 ? topK : 10, false));
    }
    catch (e) {
        board = null;
    }
    if (p.export) {
        try {
            exported = (await E.loopExport({
                path: String(p.export),
                top: 1,
                includeVariants: false,
                note: 'shape_search ' + objective,
            }));
        }
        catch (e) {
            exported = { ok: false, error: errorMessage(e).slice(0, 200) };
        }
    }
    return { board, exported };
}
//# sourceMappingURL=search.js.map