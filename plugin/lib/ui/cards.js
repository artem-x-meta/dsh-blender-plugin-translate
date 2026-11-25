import { asArray, asRecord, text } from '../contracts/dynamic.js';
export function renderOne(_args, value) {
    const v = asRecord(value);
    const blocks = [{ type: 'text', text: String(v.text || '') }];
    if (v.image)
        blocks.push({ type: 'image', attachment: v.image });
    for (const im of asArray(v.images))
        blocks.push({ type: 'image', attachment: im });
    return blocks;
}
/* ────────────────────────────────────────────────────────────────────────────
 * v0.9.3: structured receipt — **two text blocks**
 *   block 0 = the single-line JSON envelope (directly JSON.parse-able, stable fields; no need to hand-write a
 *             regex to dig it out of "human preamble + stdout tail + result: {...}" any more)
 *   block 1 = the human-readable summary (keeps the old narrative text verbatim)
 * Why two blocks: for tool results the host only passes ContentBlock[] (text/image/file) through;
 * there is no json block; and **each text block is an independent text part on the provider side**,
 * so "the first block is pure JSON" is equivalent to "the caller gets a parseable structured receipt".
 * ──────────────────────────────────────────────────────────────────────────── */
/** Safe JSON.stringify (circular refs/large objects do not blow up; returns null on failure and the caller supplies a path) */
export function safeStringify(v) {
    try {
        return JSON.stringify(v);
    }
    catch {
        return null;
    }
}
/** Truncate (keep head and tail, mark the elision in the middle) — same policy as the backend's clipMiddle */
export function clipText(s, head, tail) {
    const t = String(s == null ? '' : s);
    if (t.length <= head + tail)
        return t;
    return (t.slice(0, head) +
        String.fromCharCode(10) +
        '…[' +
        String(t.length - head - tail) +
        ' characters omitted]…' +
        String.fromCharCode(10) +
        t.slice(-tail));
}
/** Tool receipt with a structured envelope: value = {text, envelope?, image?, images?} */
export function renderStructured(_args, value) {
    const v = asRecord(value);
    const blocks = [];
    if (v.envelope) {
        const s = safeStringify(v.envelope);
        if (s)
            blocks.push({ type: 'text', text: s });
    }
    blocks.push({ type: 'text', text: String(v.text || '') });
    if (v.image)
        blocks.push({ type: 'image', attachment: v.image });
    for (const im of asArray(v.images))
        blocks.push({ type: 'image', attachment: im });
    return blocks;
}
/* ────────────────────────────────────────────────────────────────────────────
 * v2.6.1 (tool cards): presentCall / presentResult — **human-facing cards only**; not a single byte of the
 * model-side receipt (render output) changes. Without these two methods the host (dsh-TUI / Web) shows
 * 'Blender_rt_do({"code":"import bpy\n…"})' — the whole JSON argument plus the raw receipt (including the single-line JSON envelope).
 *   - call card: the title reads "Blender <action> · <key point>"; calls that carry code put the code in the card body.
 *   - result card: drops renderStructured's single-line JSON envelope (that one is there for the model to JSON.parse),
 *     puts the human-readable summary first (the TUI collapsed state shows only the first 3 lines), appends the code, and passes image blocks through as-is.
 * Pure functions depending only on args / result (the host also calls them when replaying session logs); any exception returns undefined ⇒ the host falls back to the generic card.
 * ──────────────────────────────────────────────────────────────────────────── */
const CARD_DETAIL_MAX = 48;
/** Upper bound for code in the card body (head + tail, middle elided): a script of thousands of lines should not blow the card up */
const CARD_CODE_HEAD = 3000;
const CARD_CODE_TAIL = 1000;
/** Flatten to one line and truncate (a card title holds a single line) */
function cardClip(v, max = CARD_DETAIL_MAX) {
    const one = String(v == null ? '' : v)
        .replace(/\s+/g, ' ')
        .trim();
    return one.length > max ? one.slice(0, max - 1) + '…' : one;
}
/** code → "first meaningful line (+N lines)"; an empty string when it is all comments/blank lines */
function cardCodeHeadline(code) {
    const lines = String(code == null ? '' : code)
        .split(String.fromCharCode(10))
        .map((l) => l.trim())
        .filter(Boolean);
    const first = lines.find((l) => !l.startsWith('#'));
    if (!first)
        return '';
    return cardClip(first) + (lines.length > 1 ? ' (+' + String(lines.length - 1) + ' lines)' : '');
}
/** path → file name (understands both Windows and POSIX separators) */
function cardBaseName(p) {
    const parts = String(p == null ? '' : p).split(/[\\/]/);
    return parts[parts.length - 1] || '';
}
/** rt_cmd params: list the first 3 keys of an object, clip a string to one line */
function cardParams(p) {
    if (p && typeof p === 'object' && !Array.isArray(p)) {
        const keys = Object.keys(p);
        return keys.length
            ? '{' + keys.slice(0, 3).join(', ') + (keys.length > 3 ? ', …' : '') + '}'
            : '';
    }
    return typeof p === 'string' ? cardClip(p, 32) : '';
}
/** "head · point1 · point2"; empty points are skipped */
function cardTitle(head, parts) {
    const tail = parts.map((x) => cardClip(x)).filter(Boolean);
    return tail.length ? head + ' · ' + tail.join(' · ') : head;
}
const cardSession = (a) => a.session ? 'headless ' + cardClip(a.session, 24) : '';
const cardPython = (code) => typeof code === 'string' && code.trim() ? { label: 'Python', code: code } : null;
export const CARD_SPECS = {
    blender_rt_see: {
        kind: 'read',
        title: (a) => a.full
            ? cardTitle('Blender window capture', ['area ' + String(a.area || 0)])
            : cardTitle('Blender viewport view', [
                a.from || a.look_at
                    ? 'custom view ' + cardClip(a.from || '?', 20) + ' → ' + cardClip(a.look_at || '?', 20)
                    : '',
                a.shading,
                String(a.max_size || 560) + 'px',
                cardSession(a),
            ]),
    },
    blender_rt_do: {
        kind: 'execute',
        title: (a) => cardTitle('Blender run Python', [
            a.code ? cardCodeHeadline(a.code) : cardBaseName(a.file),
            cardSession(a),
        ]),
        code: (a) => cardPython(a.code),
    },
    blender_rt_watch: {
        kind: 'execute',
        title: (a) => cardTitle('Blender continuous watch', [
            a.seconds ? String(a.seconds) + 's' : '',
            a.fps ? String(a.fps) + 'fps' : '',
            cardCodeHeadline(a.code),
            cardSession(a),
        ]),
        code: (a) => cardPython(a.code),
    },
    blender_rt_cmd: {
        kind: 'execute',
        title: (a) => cardTitle('Blender command', [a.name, cardParams(a.params)]),
    },
    blender_rt_commands: { kind: 'search', title: () => 'Blender command list' },
    blender_rt_loop: {
        kind: 'execute',
        title: (a) => cardTitle('Blender inner loop', [a.op, a.target, a.iterations ? String(a.iterations) + ' iterations' : '']),
    },
    blender_rt_perf: { kind: 'other', title: (a) => cardTitle('Blender performance', [a.op]) },
    blender_rt_opt: { kind: 'edit', title: (a) => cardTitle('Blender simplify', [a.op]) },
    blender_rt_headless: {
        kind: 'execute',
        title: (a) => cardTitle('Blender headless', [
            a.script_file ? cardBaseName(a.script_file) : cardCodeHeadline(a.script),
            cardBaseName(a.file),
            a.as_job ? 'job' : '',
        ]),
        code: (a) => cardPython(a.script),
    },
    blender_rt_plan: {
        kind: 'other',
        title: (a) => cardTitle('Blender planning', [a.op, cardSession(a)]),
    },
    blender_rt_worker: {
        kind: 'execute',
        title: (a) => cardTitle('Blender hot session', [a.op, a.name, cardCodeHeadline(a.code)]),
        code: (a) => cardPython(a.code),
    },
    blender_rt_txn: { kind: 'other', title: (a) => cardTitle('Blender transaction', [a.op, a.label]) },
    blender_rt_preset: { kind: 'other', title: (a) => cardTitle('Blender preset', [a.op, a.name]) },
    blender_rt_job: {
        kind: 'execute',
        title: (a) => cardTitle('Blender job', [
            a.op,
            a.id,
            a.script_file ? cardBaseName(a.script_file) : cardCodeHeadline(a.script),
        ]),
        code: (a) => cardPython(a.script),
    },
    blender_viewport: { kind: 'other', title: (a) => cardTitle('Blender channel', [a.op || 'status']) },
};
/** The code section in the card body: one label line + the verbatim code (head and tail kept when too long) */
function cardCodeSection(code) {
    const body = code.code.replace(/\s+$/, '');
    const n = body.split(String.fromCharCode(10)).length;
    return ('▸ ' +
        code.label +
        ' (' +
        String(n) +
        ' lines)' +
        String.fromCharCode(10) +
        clipText(body, CARD_CODE_HEAD, CARD_CODE_TAIL));
}
/** Block 0 of renderStructured: single-line JSON that parses into a plain object */
function isEnvelopeBlock(b) {
    const block = asRecord(b);
    if (block.type !== 'text' || typeof block.text !== 'string')
        return false;
    const s = block.text.trim();
    if (!s.startsWith('{') || !s.endsWith('}') || s.indexOf(String.fromCharCode(10)) >= 0)
        return false;
    try {
        const v = JSON.parse(s);
        return !!v && typeof v === 'object' && !Array.isArray(v);
    }
    catch {
        return false;
    }
}
/** For vTool: supply presentCall / presentResult by tool name (unregistered tools / ones the spec already carries are not overridden) */
export function cardPresenters(spec) {
    const s = asRecord(spec);
    const card = CARD_SPECS[text(s.name)];
    if (!card)
        return {};
    const out = {};
    if (!s.presentCall) {
        out.presentCall = (args) => {
            try {
                const a = asRecord(args);
                const view = {
                    card: 'generic',
                    title: card.title(a),
                    kind: card.kind,
                };
                const code = card.code ? card.code(a) : null;
                if (code)
                    view.content = [{ type: 'text', text: cardCodeSection(code) }];
                return view;
            }
            catch {
                return undefined;
            }
        };
    }
    if (!s.presentResult) {
        out.presentResult = (args, result) => {
            try {
                const r = asRecord(result);
                if (!r || r.isError || !Array.isArray(r.content))
                    return undefined;
                const content = asArray(r.content);
                const texts = content.filter((b) => asRecord(b).type === 'text');
                const human = texts.length > 1 && isEnvelopeBlock(texts[0]) ? texts.slice(1) : texts;
                const a = asRecord(args);
                const code = card.code ? card.code(a) : null;
                // no envelope and no code ⇒ the raw receipt is already human-readable text; let the host display it as usual
                if (human.length === texts.length && !code)
                    return undefined;
                // one text block: dsh-TUI adds no newline when it concatenates multiple text blocks
                const parts = human
                    .map((b) => String(asRecord(b).text || '').replace(/\s+$/, ''))
                    .filter(Boolean);
                if (code)
                    parts.push(cardCodeSection(code));
                const blocks = parts.length
                    ? [{ type: 'text', text: parts.join(String.fromCharCode(10, 10)) }]
                    : [];
                for (const b of content)
                    if (asRecord(b).type !== 'text')
                        blocks.push(b);
                return { card: 'generic', content: blocks };
            }
            catch {
                return undefined;
            }
        };
    }
    return out;
}
/**
 * v0.9.3: the client-side single-wait cap. Past it we **do not sit waiting**: switch to the job layer and return jobId (aligned with bash's promoted semantics).
 * Default 100 s: the outer run_code default deadline is 120 s, leaving a 20 s margin for the receipt and status queries (the promoted path is just one fast /job query).
 * Raising it = allowing a single synchronous wait to last longer (cost: when the outer deadline fires it is more likely that "the result is on the server and the client cannot get it").
 */
//# sourceMappingURL=cards.js.map
