/**
 * dsh-blender-plugin — host-side lifecycle and tool-surface assembly.
 *
 * This file only assembles: config schema / supervision / 15 tool registrations / test seams.
 * The actual implementation is split by layer across contracts/ host/ tools/ plan/ headless/ utils/ ui/.
 */
import { PLUGIN_VERSION } from './constants.js';
import { z, schemaResolve } from './contracts/tool.js';
import { losslessSanitize } from './contracts/lossless.js';
import { asRecord } from './contracts/dynamic.js';
import { resolveHttpPort } from './host/backend/index.js';
import { registerSchemaDiagnostic } from './tools/schema-diagnostic.js';
import { registerLifecycle } from './plugin-lifecycle.js';
import { registerToolSurface, registerTuiSurface } from './plugin-surfaces.js';
import { errorLine, redactSecrets, toolError } from './tools/errors.js';
import { BUNDLED_SKILL_DIR, BUNDLED_SKILL_PROVIDER, BUNDLED_SKILL_RANK, createBundledSkillProvider, parseSkillFrontmatter, readBundledSkill, registerBundledSkill, } from './host/skill.js';
import { frameDedupe, resetFrameCache } from './utils/frame-cache.js';
import { HEADLESS_WAIT_MS, headlessReceipt, promotedReceipt, receiptEnvelope, } from './headless/receipts/index.js';
import { CARD_SPECS, cardPresenters } from './ui/cards.js';
export const name = 'dsh-blender-plugin';
export const inject = ['tools'];
// v1.0.1: when z is unavailable (degraded mode) no schema is supplied — the host must not fail wholesale because of another throw here.
export const Config = z
    ? z.object({
        port: z.natural().default(resolveHttpPort()),
        autoStart: z.boolean().default(true),
        tui: z.boolean().default(true),
    })
    : undefined;
export function apply(ctx, config) {
    // v2.2.0: bundled skill auto-registration (optional capability; failure does not affect the tool surface).
    // Placed before the degraded branch — even if schemastery parsing fails and tools degrade, the skill content stays available.
    registerBundledSkill(ctx);
    // v1.0.1 (issue #10): parse failure ⇒ degrade, do not disappear (see registerSchemaDiagnostic).
    if (!z) {
        registerSchemaDiagnostic(ctx);
        return;
    }
    // Defensive config read: with a healthy schema the host fills in defaults, but neither degraded mode nor host differences should make this throw again.
    const cfgIn = asRecord(config);
    const port = Number.isFinite(Number(cfgIn.port)) && Number(cfgIn.port) > 0
        ? Number(cfgIn.port)
        : resolveHttpPort();
    const autoStart = cfgIn.autoStart === undefined ? true : !!cfgIn.autoStart;
    // Registration order must stay as in v2.6.2: TUI → supervision/backend effects → the 15 tools.
    // Cordis disposes effects in reverse order, so registering TUI/lifecycle first and tools last means unload releases tools before killing the backend.
    registerTuiSurface(ctx, port, cfgIn);
    registerLifecycle(ctx, port, autoStart);
    registerToolSurface(ctx, port);
}
/* ────────────────────────────────────────────────────────────────────────────
 * v0.9.4: **test seams**. tests/lossless_guard.mjs imports this module directly and gets
 *   ① the real receipt builders (receiptEnvelope / headlessReceipt / promotedReceipt)
 *   ② the outbound sanitizer (losslessSanitize)
 * then asserts with the **host's real validator** (snapshotJsonValue from dsh-util-values):
 * "every receipt from this plugin passes the lossless-JSON gate".
 * This is the only way to turn the "return channel" from "hope nobody writes undefined" into
 * "a machine checks it on every regression run".
 * ──────────────────────────────────────────────────────────────────────────── */
export const __internals = {
    frameDedupe: frameDedupe,
    resetFrameCache: resetFrameCache,
    losslessSanitize: losslessSanitize,
    toolError: toolError,
    redactSecrets: redactSecrets,
    errorLine: errorLine,
    receiptEnvelope: receiptEnvelope,
    headlessReceipt: headlessReceipt,
    promotedReceipt: promotedReceipt,
    HEADLESS_WAIT_MS: HEADLESS_WAIT_MS,
    PLUGIN_VERSION: PLUGIN_VERSION,
    schemaResolve: schemaResolve,
    bundledSkill: {
        dir: BUNDLED_SKILL_DIR,
        provider: BUNDLED_SKILL_PROVIDER,
        rank: BUNDLED_SKILL_RANK,
        read: readBundledSkill,
        createProvider: createBundledSkillProvider,
        register: registerBundledSkill,
        parseFrontmatter: parseSkillFrontmatter,
    },
    cards: { specs: CARD_SPECS, presenters: cardPresenters },
};
//# sourceMappingURL=plugin.js.map