// addon command catalog table (split out of catalog.ts)
export const COMMAND_CATALOG = {
    ping: { d: 'liveness probe (does not touch bpy data)', gate: null },
    get_scene_info: { d: 'scene overview (no arguments)', gate: null },
    get_world_state_snapshot: { d: 'world state snapshot: objects/selection/frame', gate: null },
    get_addon_info: { d: 'addon version and protocol number', gate: null },
    get_object_info: { d: 'single-object details (argument name)', gate: null },
    get_viewport_screenshot: { d: 'offscreen viewport screenshot (max_size, filepath, format)', gate: null },
    // resident commands of addon v1.10 (protocol number 11) — let the model look up the API instead of guessing
    describe_node_type: {
        d: 'look up all sockets/properties of a node type (bl_idname, property_overrides) — check before building shader/geometry nodes, do not guess the socket order',
        gate: null,
    },
    bpy_api_lookup: {
        d: 'look up the bpy API reference (query, e.g. "bpy.ops.mesh.primitive_cube_add")',
        gate: null,
    },
    export_scene: {
        d: 'export scene/selection/list to glb|fbx|obj (filepath, format, object_names, selection_only, apply_modifiers)',
        gate: null,
    },
    // v1.8 (plugin v2.3): Blender native selection → DSH / unified activity state
    get_activity_state: {
        d: 'unified activity state human/agent/idle/both + native selection summary (no arguments; querying itself does not count as agent)',
        gate: null,
    },
    get_selection: { d: 'current Blender native selection (name/type/active object/mode/scene; no arguments)', gate: null },
    send_selection_to_dsh: {
        d: 'POST the current selection to the DSH backend (the same implementation as the N-panel button; timeout optional)',
        gate: null,
    },
    get_collections: {
        d: 'list scene collections: name / object count / how many of them are selected (limit optional; on large assemblies pick a collection first)',
        gate: null,
    },
    send_collection_to_dsh: {
        d: 'POST a whole collection to DSH (collection optional, defaults to the N-panel dropdown\'s dshbb_collection_target)',
        gate: null,
    },
    execute_code: { d: 'execute arbitrary Python (the catch-all channel, K/bpy/math/mathutils preset)', gate: null },
    drain_human_activity: { d: 'drain the "human activity" event buffer', gate: null },
    get_telemetry_consent: { d: 'read the telemetry consent switch', gate: null },
    set_telemetry_consent: { d: 'write the telemetry consent switch (argument consent)', gate: null },
    get_polyhaven_status: { d: 'PolyHaven integration status', gate: null },
    get_hyper3d_status: { d: 'Hyper3D Rodin integration status', gate: null },
    get_sketchfab_status: { d: 'Sketchfab integration status', gate: null },
    get_polypizza_status: { d: 'Poly Pizza integration status', gate: null },
    get_hunyuan3d_status: { d: 'Hunyuan3D integration status', gate: null },
    get_polyhaven_categories: {
        d: 'PolyHaven categories (argument asset_type: hdris/textures/models)',
        gate: 'dshbb_use_polyhaven',
    },
    search_polyhaven_assets: {
        d: 'PolyHaven search (asset_type, categories)',
        gate: 'dshbb_use_polyhaven',
    },
    download_polyhaven_asset: {
        d: 'download and import a PolyHaven asset (asset_id, asset_type, resolution)',
        gate: 'dshbb_use_polyhaven',
    },
    set_texture: {
        d: 'apply an already downloaded texture to an object (object_name, texture_id)',
        gate: 'dshbb_use_polyhaven',
    },
    create_rodin_job: { d: 'Hyper3D Rodin generation job (text/image)', gate: 'dshbb_use_hyper3d' },
    poll_rodin_job_status: { d: 'poll a Rodin job', gate: 'dshbb_use_hyper3d' },
    import_generated_asset: { d: 'import a Rodin generation result', gate: 'dshbb_use_hyper3d' },
    search_sketchfab_models: {
        d: 'Sketchfab search (query, categories, count)',
        gate: 'dshbb_use_sketchfab',
    },
    get_sketchfab_model_preview: { d: 'Sketchfab model preview image', gate: 'dshbb_use_sketchfab' },
    download_sketchfab_model: { d: 'download and import a Sketchfab model (uid)', gate: 'dshbb_use_sketchfab' },
    search_polypizza_models: { d: 'Poly Pizza search (query)', gate: 'dshbb_use_polypizza' },
    download_polypizza_model: {
        d: 'download and import a Poly Pizza model (model_id)',
        gate: 'dshbb_use_polypizza',
    },
    create_hunyuan_job: { d: 'Hunyuan3D generation job', gate: 'dshbb_use_hunyuan3d' },
    poll_hunyuan_job_status: { d: 'poll a Hunyuan3D job', gate: 'dshbb_use_hunyuan3d' },
    import_generated_asset_hunyuan: { d: 'import a Hunyuan3D generation result', gate: 'dshbb_use_hunyuan3d' },
};
// Wire-only addon commands that are deliberately not model-facing . Declared
// here so the host catalog <-> addon registry parity is checkable in both
// directions; addon/dsh_blender_bridge/command_registry.py COMMAND_NAMES stays
// the only command truth. Consumed by tests/unit/js/contract/command-contract.test.ts
// and tests/integration/python/test_addon_command_matrix.py.
export const COMMAND_CATALOG_OMISSIONS = ['get_polyhaven_asset_preview'];
//# sourceMappingURL=commands.js.map