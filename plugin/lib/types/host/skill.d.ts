import type { HostContext } from './context.js';
export declare const BUNDLED_SKILL_PROVIDER = "dsh-blender-plugin";
export declare const BUNDLED_SKILL_RANK = 600;
export declare const BUNDLED_SKILL_DIR: string;
export interface BundledSkill {
    name: string;
    description: string;
    content: string;
}
export interface BundledSkillProvider {
    name: string;
    list: () => Promise<unknown[]>;
    get: () => Promise<unknown>;
}
/** Parse the YAML frontmatter of SKILL.md (only the name/description this plugin needs; no yaml dependency is pulled in). */
export declare function parseSkillFrontmatter(raw: string): {
    meta: Record<string, string>;
    body: string;
};
export declare function readBundledSkill(): BundledSkill | null;
export declare function createBundledSkillProvider(): BundledSkillProvider | null;
/**
 * Register the bundled skill in the host's skills registry (an optional capability; failures only warn).
 * Use ctx.inject(['skills'], cb) to defer registration until the service is available: if the host has no skill service,
 * this child fiber simply stays on standby and **never** prevents the plugin itself from starting.
 */
export declare function registerBundledSkill(ctx: HostContext): void;
