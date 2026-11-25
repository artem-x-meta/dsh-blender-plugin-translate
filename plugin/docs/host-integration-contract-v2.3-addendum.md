# Host integration · Interface contract v2.3 supplement — Blender native selection → DSH · unified activity verdict

> **v2.6 compatibility statement (2026-10-20)**: this contract (v2.3 supplement) under plugin **v3.0.0** **still applies**;
> the addon is currently **v1.11 / protocol 11** (new commands are backward compatible, old addons can still connect).
> The P0–P2 capabilities added in v2.4–v2.6 (interactive headless worker/see/watch, reference-image measuring tools `img_*`, assembly `asm_*`,
> blockout `blockout_*`, same camera position QC `visualreport_report`, headless silhouette fitting `shapesolve_solve`, flaw evaluation `eval_run`,
> hard gate `gate_preflight/checkpoint/deliver` + `deliver_export(require_gate)`, worker idle TTL, etc.)
> **do not change** this contract's selection / activity / host routing semantics; for new ops, `blender_rt_plan(op="catalog")` (**34 families / 228 ops**) is authoritative.
> The contract body (§S0–§S3) is kept as is; the version annotations below (such as "since v1.8", "v2.5 for addon v1.11") are historical notes.

> **Status**: the implementation baseline of v2.3.0 (2026-10-19); §S6 (the dsh-TUI host half) is a v2.6.1 supplement. This file is the **single source of truth**: when the implementation (addon / backend / client / TUI host half),
> the self-tests (`tests/selection_store_selftest.mjs`, `tests/host_routes_selftest.mjs`, `tests/client_bundle_selftest.mjs`, `tests/tui_host_selftest.mjs`)
> and the documentation conflict, this file wins; changing the contract requires changing the tests in sync.
>
> This file is the current sole interface contract (the v1.2/v2.1/v2.2 historical contract documents were deleted together with the viewport panel / click-picking in v2.3).
> Old field semantics are not retained: the `/host/view/*`, `/host/pick*`, `/host/ready` routes and `blender_rt_pick` have all been removed.

---

## §S0 Background and goals

The "selection" of v1.x–v2.2 was **clicking a screenshot on the DSH side**: click the image in the DSH panel → `POST /host/view/pick` back-projection → "add to message".
Measured in practice, it had three pain points: the image is small / goes stale, clicking small parts is inaccurate, and you must switch windows.

v2.3 moves the **selection entry point to the Blender side** (an explicit user choice):

1. The user selects objects in the **Blender native selection** (click, box select, Shift add — all fine);
2. Press `N` in the 3D viewport → "DSH Blender Bridge" → **Selection → DSH** → "Send selection to DSH";
3. The addon **POSTs** the selection to the DSH backend; the Web client half **inserts it into the current session draft** (**does not auto-send**);
4. At the same time the addon decides the four states **human / agent / idle / both** on the Blender side in one place (modal operators, recent human operations, agent command window),
   displays them live in the panel, and the model can query them via `blender_rt_cmd get_activity_state`.

**Deleted in the same version**: the DSH-side viewport panel (Web sidebar + TUI sidebar), click-into-message, and model-requested click-picking `blender_rt_pick` are all removed
(model tools 16 → **15**); the backend `/host/view/*`, `/host/pick*`, `/host/ready` routes are **deleted in sync**.
The only host routes that remain are: `/host/selection` (+ `/latest`, `/consume`), `/host/scene-items` (the `@` mention data source),
`/host/jobs` (+ `/log`).
The two selection entry points are unified into the N panel's **multi-select mode / collection mode**.

> All that is retained is the `@` mention (`GET /host/scene-items`); screenshot click-picking, `blender_rt_pick` and `/host/view/*`, `/host/pick*`, `/host/ready` were deleted together with the panel.

---

## §S1 addon side (since v1.8, protocol number still 11; v2.5 is addon v1.11)

### §S1.1 New commands

| Command | Parameters | Returns |
|---|---|---|
| `get_activity_state` | none | activity snapshot (see §S1.2). **The query command itself does not count as agent**. |
| `get_selection` | none | `{count, names, truncated, active, mode, objects, scene, file, activity}` |
| `send_selection_to_dsh` | `timeout?` (seconds, default 3.0) | `{ok, seq?, received_at?, status_code?, error?, hint?, backend_url, payload}` |
| `get_collections` | `limit?` (default 200) | `{count, returned, collections:[{name,count,selected_count,parent}], scene}` |
| `send_collection_to_dsh` | `collection?` (defaults to the scene property `dshbb_collection_target`), `timeout?` | same as `send_selection_to_dsh`, but `selection.kind="collection"` |

- All three are **resident commands** (not gated behind the 5 integrations), and are included in `get_addon_info.capabilities`.
- All of them go through the Blender main thread (same class as `get_scene_info`; during a render they hit the existing `BUSY_RENDER` semantics first).
- addon version **v1.8**; `bl_info["version"] = (1, 8)`; the protocol number stays **11** (new commands are backward compatible, old plugins can still connect).

### §S1.2 activity snapshot (unified state)

```json
{
  "state": "idle | human | agent | both",
  "human_active": false,
  "agent_active": false,
  "human_idle_ms": 1234,
  "agent_idle_ms": 567,
  "last_human_kind": "operator:object.select_all | selection | undo | modal:transform.translate | null",
  "agent_depth": 0,
  "modal_operators": ["transform.translate"],
  "mode": "OBJECT",
  "selection": {"count": 2, "names": ["Cube", "Camera"], "active": "Cube", "mode": "OBJECT", "truncated": false},
  "windows_ms": {"human": 1500, "agent": 1500},
  "scene": "Scene",
  "ts": 1792415489.9,
  "source": "addon"
}
```

**Verdict rules** (`ActivityTracker` in `addon/dsh_blender_bridge/recorders/activity.py`):

- **human signal**: `bpy.context.window.modal_operators` non-empty (drag/transform/menu and other modal operations, **persistently valid**) ·
  a human operator appeared within the last 1.5 s (including view3d navigation filtered out by `_IGNORED_OPERATORS`) · undo/redo ·
  native selection / active object / mode change (1.5 s window).
- **agent signal**: inside `UserEditRecorder.agent_command()` (`agent_depth > 0`), or the last agent command ended ≤1.5 s ago.
- **attribution rules**: human signals are suppressed during an agent command; at command end the selection fingerprint is invalidated (otherwise every tool call would falsely report `human`).
- **the query itself**: `get_activity_state` / `get_selection` use `include_current_command=false` — the state **does not include this query**,
  otherwise the model would see `state=agent` on every query.
- **privacy**: decided locally only, **does not depend on telemetry_consent, uploads nothing**. This is a different thing from `drain_human_activity` (which only has events after telemetry consent).

### §S1.3 selection payload (addon → backend)

```json
{
  "v": 1,
  "source": "blender-addon",
  "sent_at": 1792415489912,
  "selection": {
    "count": 2,
    "names": ["Cube", "Camera"],
    "truncated": false,
    "active": "Cube",
    "mode": "OBJECT",
    "objects": [
      {"name": "Cube", "type": "MESH", "dimensions_mm": [2000, 2000, 2000]},
      {"name": "Camera", "type": "CAMERA", "dimensions_mm": [0, 0, 0]}
    ]
  },
  "scene": {"name": "Scene", "file": "machine.blend"},
  "activity": { "...§S1.2 snapshot..." }
}
```

- `names` is capped at 200, `objects` at 50, `collections` at 50 (the addon truncates first, the backend truncates again); `file` only gives the **basename**.
- **collection payload** (`send_collection_to_dsh` / N panel collection mode): `selection.kind="collection"`, `selection.collection="<name>"`,
  `count`=total number of objects in the collection, `names`=the first 200 members; the client draft text is "Blender collection: <name> (N items, first k: ...)".
- **N panel's two modes**: scene property `dshbb_selection_mode = "MULTI" | "COLLECTION"` (default MULTI).
  MULTI shows the **object list** of the current selection and sends `kind="objects"`;
  COLLECTION shows a collection dropdown (`dshbb_collection_target`, PointerProperty) + **member list** + item count + sub-collection summary,
  and sends `kind="collection"`. When switching to COLLECTION with no collection chosen, the `update` callback automatically picks "the collection in which the selected objects appear most often";
  the panel's ⟳ button (`dshbb.use_selection_collection`) re-infers at any time.
- **list UI (v2.3.1+)**: the object / member lists are collapsed by default; expanded they are a Blender `UIList` (with its own scrollbar),
  height controlled by the scene property `dshbb_list_rows` (3–30, default 8); the backend address is tucked into the collapsed "Backend / Advanced".
- **sub-element payload (v2.4, `selection.sub`)**: attached when sending from edit mode / pose mode, structured as follows:

```json
"sub": {
  "type": "MESH",                 // MESH | ARMATURE | CURVE | LATTICE | OTHER
  "object": "Cube",
  "mode": "EDIT_MESH",
  "select_mode": {"vertex": true, "edge": false, "face": false},
  "counts": {"vertices": 12, "edges": 0, "faces": 0},
  "indices": {"vertices": [0, 3, 7], "edges": [], "faces": []},
  "bones": ["Bone.001"],          // when type=ARMATURE
  "points": [[0, 2], [0, 5]],     // when type=CURVE/LATTICE these are (spline_index, point_index)
  "truncated": false
}
```

  The addon-side cap per index class is **2000**, bone names **500**; the backend clamps once more and filters non-integers/negatives.
  UI state such as the backend address and panel lists does not enter the payload.
- Backend address: `DSH_BLENDER_BACKEND_URL` env var → scene property `dshbb_backend_url` → default `http://127.0.0.1:9877`.
- The N panel button and the `send_selection_to_dsh` command are **the same implementation** (the button just calls it internally). A send failure shows the reason in the panel, no popup.

---

### §S1.4 Pause AI operations (v2.5, addon v1.11)

- Scene property `dshbb_ai_paused` (Bool, default `False`) + operator `dshbb.toggle_ai_pause`; toggled by the button at the top of the N panel.
- While paused the socket **only lets read-only commands through**: `ping`, `get_*`, `drain_human_activity`, `describe_node_type`, `bpy_api_lookup`;
  everything else (`execute_code`, asset download/generate/import, `send_*`, `set_*`, etc.) returns
  `{"status":"error","error":"AI_PAUSED","message":"…"}`.
- The `get_activity_state` receipt gains `paused: true|false`; while paused the model cannot lift it itself, a human must click "Resume AI operations" in the Blender panel.
- Scope: only affects the GUI addon socket; headless Blender processes / the file system are unaffected.

---

## §S2 Backend routes (zero Blender round-trips)

All three live under `/host/*` and follow the CORS rules of base contract §1.1 (ACAO is echoed only for loopback / `dsh-app://app`).

### §S2.1 `POST /host/selection` — the addon pushes a selection

- Request body: §S1.3 payload (`content-type: application/json`).
- `200` → `{"ok": true, "seq": 3, "received_at": 1792415489920}`
- `400` → `{"ok": false, "error": "invalid_payload"}` (not an object / parse failure)
- **Does not check the write lease**: this is a user-side push (same class as `/host/view/pick`) and performs no scene write.
- Storage-layer sanitizing: name/string truncation (`MAX_STRING_CHARS=200`), count caps, unknown fields dropped (`runtime/selectionstore.mjs`).

### §S2.2 `GET /host/selection/latest` — client polling

```json
{
  "ok": true,
  "seq": 3,
  "consumed_seq": 2,
  "unconsumed": true,
  "received_at": 1792415489920,
  "stale_ms": 412,
  "selection": { "...§S1.3.selection..." },
  "activity": { "...§S1.2..." },
  "scene": {"name": "Scene", "file": "machine.blend"},
  "last_consume": {"seq": 2, "ok": false, "how": null, "reason": "draft already has content, the fallback channel does not overwrite", "at": 1792415488711}
}
```

- **`selection/activity/scene` are included only when `unconsumed=true`** (to avoid re-inserting an old selection after a page reload).
- `last_consume` is a **diagnostic field**: the client reports the insertion result back (see §S2.3),
  used to answer "the button was clicked and the backend received it, so why is there no text in the draft".
- Pure in-memory, zero I/O; the `since` parameter is no longer needed (consumers use the CAS semantics of `unconsumed` + `consume`).

### §S2.3 `POST /host/selection/consume` — mark as inserted

- Request body: `{"seq": 3, "ok": true, "how": "actions"}`; `ok/how/reason` are optional (legal for curl / old clients).
- `200` → `{"ok": true, "consumed_seq": 3}`; illegal seq (0 / negative / future / non-integer) → `400 {"ok": false, "consumed_seq": N, "error": "invalid_seq"}`.
- `consumed_seq` **only increases, never decreases**; consuming the same seq repeatedly is idempotent.
- Multi-tab race: the server dedupes by seq; in extreme cases the same selection may be inserted once by each of two clients (known boundary, see §S5).

---

## §S3 Client half (Web)

### §S3.1 Where the headless bridge sits

- Registered on `conversation.input.dock` (**session scoped, permanently mounted, renders `null`**),
  id `blender-selection-bridge`, order 90.
- Therefore: **it keeps receiving even with the sidebar panel collapsed**; the user does not need to open the DSH panel first.
- Each open session mounts its own bridge; only the **current session** inserts (`inject`'s `sessionId` decides the target).

### §S3.2 Polling and insertion

1. `GET /host/selection/latest` every **100 ms** (`no-store`); failures are silent, retried on the next tick.
   (v2.6.1 performance, measured in practice: end-to-end p50 ~993 ms at 1200 ms, ~156 ms at 100 ms; the local GET cost of 10 req/s for a single client is negligible.)
2. `unconsumed === true` and `seq` not yet processed → generate the draft text:
   `Blender selection: <names, comma-separated> (N total, only the first M listed). Active object: X. Mode: OBJECT. When the user says "this/these", they mean them; object names are directly usable in bpy.data.objects.`
3. Write into the current session draft (**does not auto-send**):
   - prefer `inputActions.insertText(text, captureInsertion())` (appendable, preserves what the user already typed);
   - fallback `SessionInput.setDraft(text)`: **only writes when it is readable and the draft is empty**, never overwrites user content.
4. Insertion succeeded → `POST /host/selection/consume {seq, ok:true, how}`.
5. Insertion failed → **do not consume**, retry on the next tick (at most 3 times; on the 3rd, consume and report `ok:false, reason`, to avoid getting stuck).
6. Notify "Received Blender selection (added to draft, not sent)" via `fallbackInput.notify("info", …)` (when the service is available).

### §S3.3 What it does not do

- Does not auto-send messages, does not create sessions, does not touch other sessions' drafts.
- Does not poll Blender (zero bpy round-trips); does not require the DSH sidebar panel to be open.
- Keeps polling while the page is in the background (the user may click the Blender button and switch straight back to DSH).

---

## §S4 Acceptance criteria (re-runnable)

| # | Criterion | How to check |
|---|---|---|
| S1 | addon v1.8 has 3 new commands | `blender_rt_cmd get_addon_info` → `addon_version=[1,8]` and capabilities contain the three |
| S2 | activity four states + window | `blender_rt_cmd get_activity_state` → `state=idle` when idle; `agent_active=true` within 1.5 s after an agent command; `human_active=true` + non-empty `modal_operators` during a modal operation |
| S3 | native selection is readable | select in Blender → `blender_rt_cmd get_selection` → `names` match the viewport |
| S4 | button → backend | click the panel button (or `bpy.ops.dshbb.send_selection_to_dsh()`) → `curl /host/selection/latest` has a `seq` |
| S5 | backend sanitizing | `POST /host/selection` with a non-object → 400; over-long names truncated to 200; `consume(0)` → 400 |
| S6 | client insertion | restart/refresh DSH then click the button → text appears in the current session draft; `/host/selection/latest.last_consume` returns `{ok:true, how:"actions"}` |
| S7 | no auto-send | after insertion the message is **not** sent (still a draft) |
| S8 | no Blender does not block | backend up, Blender down: `/host/selection/*` still readable and writable (pure memory) |
| S9 | N panel's two modes | switch to "multi" → sends the selected objects; switch to "collection" → pick a collection → sends the whole group; the draft texts are the object name list / the collection summary respectively |
| S10 | collection commands | `blender_rt_cmd get_collections` returns collections and counts; `send_collection_to_dsh {collection:"COL"}` → backend `seq` |

Automated regression: inside `npm test`
`tests/selection_store_selftest.mjs` (storage / sanitizing / consume) · `tests/client_bundle_selftest.mjs` (text / insertion / seating) ·
`tests/host_routes_selftest.mjs` (the real HTTP part of criteria S1–S8; not in npm test, run it manually).

---

## §S5 Known boundaries (recorded as they are)

1. **The client half needs a DSH restart (or page refresh)**: `lib/client.js` is a module loaded at startup; HMR may hot-load during development, but a real upgrade requires a restart.
2. **TUI draft**: `conversation.input.dock` is a Web client seat; dsh-TUI does not load the client half.
   Since v2.6.1 the host-side TUI host half takes over (see §S6): the selection is attached to the next message as a **context chip**, which requires dsh-TUI to provide a
   `tuiContextChips` seam; on dsh-TUI versions without that seam the old behavior remains (the backend receives it, nothing appears in the TUI). **The TUI-side viewport panel was deleted in v2.3 and is not being restored.**
3. **Only enters the "current session"**: the bridge is mounted on the currently open session; if the user switches to another session and then clicks the Blender button, it goes into the draft of the session switched to.
4. **Background polling**: polling continues at 100 ms while the page is hidden (for the "click and switch straight back" scenario); v2.6.1 measured an end-to-end p50 of ~156 ms at that interval. If you care extremely about hidden-page power draw, a configurable switch can be added later.
5. **Multiple tabs**: in extreme cases the same seq may be inserted once by each of two tabs; the server does not lie, `last_consume` keeps the last one.
6. **Old addons**: v1.7 and earlier do not have these 3 commands → the button does not exist and `get_selection` reports unknown; the model tool surface is unaffected.
7. **Sub-element granularity**: currently expanded to mesh (vertex/edge/face), armature (edit/pose bones), curve/surface control points, lattice points;
   text/grease pencil and other edit modes only carry `type:"OTHER"` + note and do not pretend to know which elements are selected.
   Sub-element selection changes **do not enter the activity fingerprint** (activity is still decided at object-selection level, not scanned tick by tick);
   while a list is expanded a timer syncs the UIList content every 0.5 s (expanding a large mesh has enumeration overhead; collapsing stops it).
8. **Seat conflicts from hot reload / duplicate plugins**: registering the same id twice raises an error from the slots layer; a single load in production does not hit this (during development, a restart is the fix).

---

## §S6 dsh-TUI host half (v2.6.1)

dsh-TUI does not load `lib/client.js`, so §S3's client half does not exist in the TUI. v2.6.1 provides the same experience on the **host side** (`src/tui/*`, same process as the model tools)
using dsh-TUI's host seams. It does **not restore** the viewport panel / click-picking, and does not change the inputs of the 15 tools or the model-side receipts.

### §S6.1 Enablement rules

- Every block lazily waits for its service via `ctx.inject([...])`: if the host does not have it, it is never enabled (zero impact on Web / headless / older dsh-TUI).
- The plugin line config `tui: false` turns it all off (default `true`).
- `blender_viewport(op="doctor")` gains a line "TUI host half: selection chip ✅ · footer ✅ · @ mentions ✅ · /blender ✅",
  and states "not enabled" on non-dsh-TUI hosts.

| Block | Host seam | Behavior |
|---|---|---|
| selection → chip | `tuiContextChips.attachContext` (new dsh-TUI seam) | polls `/host/selection/latest` every 100 ms; re-sending under the same key `selection` **replaces** the previous chip |
| toast | `tuiToast.show` (optional) | "Received Blender selection · attached to the next message (not sent)"; hints once when it cannot attach |
| footer field | `tuiStatus.setField` (since dsh-TUI #1628) | reads `/host/state` every 3000 ms, writes only when the content changed; `right-head`, ≤ 24 cells, hidden below 60 columns |
| `@` mention | `tuiMentions.register` (new dsh-TUI seam) | the first query pulls one full `/host/scene-items` (≤ 1000 entries) into cache, afterwards local filtering returns immediately, and a cache older than 5 s refreshes in the background; the inserted text uses the same convention as the Web codec's `serialize`: `<blender-object>name</blender-object>` (same for materials / collections) |
| `/blender` | `commands.register` (DSH core, also in Web) + `tuiCommandTrees` (completion) | `status` (default, zero Blender round-trips) / `doctor` (actually runs one bpy round-trip) / `jobs` |

### §S6.2 selection → chip semantics

The same CAS as §S3.2: **consume only after attaching** `consume {seq, ok:true, how:"tui-chip"}`; if it cannot attach, do not consume and retry on the next tick,
and on the 3rd failure `consume {ok:false, reason}`. Only two differences:

- The write target is a **context chip** instead of draft text: the chip is sent to the model with the user's **next** message (`<attached-context source="plugin" …>`),
  the user can delete it, and it is **not auto-sent**; the text is word-for-word identical to §S3.2 step 2 (`tests/tui_host_selftest.mjs` cross-checks `lib/client.js`).
- An empty selection consumes directly with `consume {ok:false}` (there is nothing to retry), instead of idling 3 times.

### §S6.3 `GET /host/state` (zero Blender round-trips)

Reads only `engine.metrics()`, the lease table, the render_guard marker files and the job ledger from memory:

```json
{
  "ok": true,
  "channel": { "lastOkAgeMs": 812, "lastCmd": "execute_code", "lastCmdAgeMs": 812, "inflight": 0,
               "lastError": null, "lastErrorAgeMs": null, "diagnosis": null, "aiPaused": false },
  "lease": { "...same shape as /who's lease..." },
  "render": { "busy": false, "ageMs": null, "scene": null },
  "jobs": { "running": 0 },
  "backend": { "pid": 4242, "uptimeMs": 61234 }
}
```

- `aiPaused`: set to `true` when the addon's "Pause AI operations" rejects a command (the protocol layer only leaves the message "AI operations are paused: …"), **cleared on the next success**.
  The backend does not poll Blender for it, so after pausing it only shows up once the next AI action is rejected.
- `channel.lastOkAgeMs === null` = the GUI channel has never succeeded in this backend process (the footer shows "not connected").

### §S6.4 Footer priority

`backend unreachable ○` → `AI paused ⏸` → `rendering` → `main thread busy` → `not connected ○` → `someone else's lease` → `●` (normal); while headless jobs are running, "· job N" is appended to the text.
The hover description states the cause and the fix (`detail`, ≤ 160 cells).

### §S6.5 Known boundaries

1. The chip only enters the **currently bound session**; when not yet in a session (launchpad) it cannot attach, and after 3 times it is consumed as a failure (consistent with the Web's "only the current session").
2. When the Web client and dsh-TUI are connected to the same backend, both poll, and whichever attaches first consumes (same as §S5.5).
3. `@` mentions: dsh-TUI gives only about 300 ms per query, while `/host/scene-items` needs at least two bpy round-trips (module probe + query, plus injection on the first call), so a direct query often times out.
   Hence the cache (§S6.1 table): **the cold-start one** mostly times out and returns empty, but the cache gets filled and the next keystroke has results; after an object rename it takes up to 5 s to show in the candidates.
   Blender is only touched when the user types `@`, no polling.
4. The `tuiContextChips` / `tuiMentions` seams on the dsh-TUI side are submitted separately in ccch1mneyyy/dsh-TUI; until the seams land, the corresponding blocks stay disabled.

