import { vTool } from '../../contracts/tool.js';
import { ANY_SCHEMA } from '../schema-diagnostic.js';
import { T } from '../../constants.js';
import { renderOne } from '../../ui/cards.js';
import { executeWatch } from './execute.js';
export function registerWatch(ctx, port) {
    ctx.effect(() => ctx.tools.register(vTool({
        name: 'blender_rt_watch',
        description: 'Observe a time window / frame sequence: run code first, then sample up to 6 frames plus a per-frame hash (to tell whether animation or modifiers moved); falls back to a headless worker when the GUI is unavailable.',
        parameters: {
            code: { type: 'string', description: 'Optional: Python to run before observing' },
            seconds: { type: 'number', description: 'Observation duration, default 2 s (0.2-20)' },
            fps: { type: 'number', description: 'Sampling rate, default 4 (0.5-8)' },
            max_size: { type: 'integer', description: 'Longest-edge pixels of the frame, default 420' },
            session: { type: 'string', description: 'Headless worker session (if omitted, a GUI failure degrades automatically)' },
        },
        output: { schema: ANY_SCHEMA, render: renderOne },
        isConcurrencySafe: () => false,
        timeoutMs: T.watch,
        async execute(args) {
            return executeWatch(ctx, port, args);
        },
    })), 'dsh-blender-plugin: rt-watch');
}
//# sourceMappingURL=register.js.map