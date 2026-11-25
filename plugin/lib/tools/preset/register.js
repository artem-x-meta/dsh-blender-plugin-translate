import { vTool } from '../../contracts/tool.js';
import { ANY_SCHEMA } from '../schema-diagnostic.js';
import { T } from '../../constants.js';
import { renderOne } from '../../ui/cards.js';
import { executePreset } from './execute.js';
export function registerPreset(ctx, port) {
    ctx.effect(() => ctx.tools.register(vTool({
        name: 'blender_rt_preset',
        description: '[Recipe library] turn "parameter combinations" into assets you can save, apply and share: save / list / get / apply / delete / export / import / help.' +
            'data is expressed as dot paths: material nodes {"inputs.Base Color": [1,0,0,1]}, object properties {"location": [0,0,1]}, scene settings {"render.resolution_x": 640}.' +
            'targets for apply uses MAT:material name / OBJ:object name / SCENE (comma-separated); without targets it only previews (dry_run), with targets it writes for real and reports applied/skipped/errors.' +
            'export/import go through a single JSON bundle, convenient for sharing a recipe with another machine or session.',
        parameters: {
            op: {
                type: 'string',
                required: true,
                description: 'save | list | get | apply | delete | export | import | help',
            },
            name: { type: 'string', description: 'recipe name (save / get / apply / delete)' },
            kind: {
                type: 'string',
                description: 'category (list can filter by kind), e.g. material / object / scene',
            },
            tags: { type: 'string', description: 'tags (comma-separated; list can filter by tag)' },
            note: { type: 'string', description: 'note (save)' },
            data: {
                type: 'string',
                description: 'dot-path JSON string (save), e.g. {"inputs.Roughness": 0.4}',
            },
            targets: {
                type: 'string',
                description: 'apply targets (comma-separated): MAT:material name / OBJ:object name / SCENE',
            },
            path: { type: 'string', description: 'export output path / import input path' },
            names: { type: 'string', description: 'recipe names selected by export (comma-separated; omit = all)' },
            overwrite: { type: 'boolean', description: 'whether save/import overwrites an existing name (default true)' },
        },
        output: { schema: ANY_SCHEMA, render: renderOne },
        isConcurrencySafe: () => false,
        timeoutMs: T.preset,
        async execute(args) {
            return executePreset(port, args);
        },
    })), 'dsh-blender-plugin: rt-preset');
}
//# sourceMappingURL=register.js.map