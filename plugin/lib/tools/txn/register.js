import { vTool } from '../../contracts/tool.js';
import { ANY_SCHEMA } from '../schema-diagnostic.js';
import { T } from '../../constants.js';
import { renderOne } from '../../ui/cards.js';
import { executeTxn } from './execute.js';
export function registerTxn(ctx, port) {
    ctx.effect(() => ctx.tools.register(vTool({
        name: 'blender_rt_txn',
        description: '[Transactions / rollback] Two-level snapshots: **file level** snapshot/restore (whole-scene rollback; writes a .blend copy, with copy=True so the current filepath is not changed; large scenes cost MBs — measured in practice on a 300-object project on this machine at about 97MB / 0.8s) + **object level** mark/revert (records only transform / material slots / visibility / modifier toggles, millisecond-scale, in-place rollback).' +
            'Use it when you want to "drop a marker before tearing down the whole scene" (snapshot) or "change one thing and compare" (mark, then revert).' +
            'restore defaults to into="auto": after loading the snapshot the session is put back on **the file the snapshot came from** (saves land back in its own project, not in the snapshot directory), and a pre_restore backup is taken automatically before loading; into="snapshot" is non-destructive (just a look, the original file is not written).' +
            '⚠️ Limits: object level does **not cover topology/UV/vertex-level changes** — after a boolean, join or face deletion there is no way back (revert skips those and reports it); for that kind of rollback use file-level snapshot/restore.',
        parameters: {
            op: {
                type: 'string',
                required: true,
                description: 'snapshot | restore | list | prune | mark | revert | marks | drop | help',
            },
            label: { type: 'string', description: 'snapshot / mark name (a timestamp is used if snapshot omits it)' },
            objects: { type: 'string', description: 'limit the objects for mark (comma-separated; omitted = whole scene)' },
            keep: { type: 'integer', description: 'prune keeps only the N most recent snapshots, default 5' },
            note: { type: 'string', description: 'snapshot note' },
            into: {
                type: 'string',
                description: 'restore write-back target: auto (default, back to the file the snapshot came from) | snapshot (non-destructive, original file not written) | original (must be writable, otherwise it fails)',
            },
            backup: {
                type: 'boolean',
                description: 'whether restore takes a pre_restore backup automatically beforehand (default true)',
            },
        },
        output: { schema: ANY_SCHEMA, render: renderOne },
        isConcurrencySafe: () => false,
        timeoutMs: T.txn,
        async execute(args) {
            return executeTxn(port, args);
        },
    })), 'dsh-blender-plugin: rt-txn');
}
//# sourceMappingURL=register.js.map