/** blender_rt_see tool declaration and registration (schema/parameter descriptions are the model contract, kept verbatim). */
import { vTool } from '../../contracts/tool.js';
import { ANY_SCHEMA } from '../schema-diagnostic.js';
import { T } from '../../constants.js';
import { renderOne } from '../../ui/cards.js';
import { executeSee } from './execute.js';
function buildSeeTool(ctx, port) {
    return vTool({
        name: 'blender_rt_see',
        description: '[see viewport] about 55–160 ms per frame: use it to change one step and look at the result. When the GUI is not there or a session is passed, it automatically uses the offscreen Workbench of the persistent worker (so it works headless too).' +
            'Give from/look_at (optionally with lens / ortho / ortho_scale / view_size / shading / overlays / view_mode) for a **custom view**: it builds its own matrix and draws offscreen, creates no camera, does not touch scene.camera and does not move the user viewport.' +
            'full=true + area=N takes a whole-window screenshot (use it when you want to see the Blender UI). The receipt carries coverage_estimate and the frame_looks_empty self-diagnosis; an identical frame is not re-attached by default (saves vision tokens), pass force=true to resend it.' +
            'For parameter details see blender_rt_plan(op="catalog", args={tool:"rt_see"}).',
        parameters: {
            max_size: {
                type: 'integer',
                description: 'longest-edge pixels, 560 by default (420 is faster, 900 is sharper)',
            },
            session: { type: 'string', description: 'headless worker session name (does not go through the GUI)' },
            auto: { type: 'boolean', description: 'fall back to headless see when the GUI is unavailable (true by default)' },
            full: {
                type: 'boolean',
                description: 'whole-window/region screenshot (screenshot_area path): use it to see the Blender UI or another editor; false by default = 3D viewport offscreen frame',
            },
            area: { type: 'integer', description: 'region index when full=true, 0 by default (the first region)' },
            from: {
                type: 'string',
                description: '[custom view] camera position "x,y,z" (world coordinates). Given from + look_at it renders a custom view: applies a self-built matrix and draws offscreen, touching no object and no user viewport — use it to "look from the other side" or for multi-angle checking (about 100ms)',
            },
            look_at: { type: 'string', description: '[custom view] the point to look at, "x,y,z"' },
            lens: { type: 'number', description: '[custom view] focal length in mm, 50 by default' },
            ortho: { type: 'boolean', description: '[custom view] orthographic projection (used together with ortho_scale)' },
            ortho_scale: {
                type: 'number',
                description: '[custom view] orthographic scale (fits the long edge), 10 by default',
            },
            view_size: {
                type: 'string',
                description: '[custom view] resolution "widthxheight", e.g. "1280x720"; 16:9 from max_size by default',
            },
            shading: {
                type: 'string',
                description: '[custom view] temporarily switch shading to WIREFRAME/SOLID/MATERIAL/RENDERED (restored after the frame)',
            },
            overlays: {
                type: 'boolean',
                description: '[custom view] temporarily toggle overlays (grid/axes/gizmo), restored after the frame',
            },
            view_mode: {
                type: 'string',
                description: '[custom view] viewport (default, zero scene changes, exactly what the viewport shows) / render (temporary camera + fast Workbench render)',
            },
            diagnostics: {
                type: 'boolean',
                description: '[custom view] whether to force the three diagnostics (coverage_estimate / scene_bbox / objects_in_frame). Off by default (saves 45–490 ms per call); a nearly empty frame automatically runs them once more to keep the frame_looks_empty warning. Pass true to check coverage frame by frame',
            },
            force: {
                type: 'boolean',
                description: 'when the previous frame and this frame have exactly the same hash, the image is **not re-attached** by default (saves model-side tokens); pass true to force resending this image',
            },
        },
        output: { schema: ANY_SCHEMA, render: renderOne },
        isConcurrencySafe: () => true,
        timeoutMs: T.see,
        async execute(args) {
            return executeSee(args, ctx, port);
        },
    });
}
export function registerSee(ctx, port) {
    ctx.effect(() => ctx.tools.register(buildSeeTool(ctx, port)), 'dsh-blender-plugin: rt-see');
}
//# sourceMappingURL=register.js.map
