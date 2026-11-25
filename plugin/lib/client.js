/**
 * dsh-blender-plugin — client half (browser bundle).
 *
 * Hand-written, zero bundler, zero new dependencies (contract §0 / §2.2). This file **is** the bundle source:
 * `scripts/build-client.mjs` copies it verbatim to `lib/client.js`, exposed to the DSH host by
 * `package.json` `dsh.client` + `exports["./client"]`.
 *
 * Wrapper format copied verbatim from the third-party sample already running locally,
 * `@dsh-external/dsh-coc-dice/lib/client.js`:
 *   window.__ModuleLoader__.load({ id, factory: (require) => { … return module.exports } })
 * Loader semantics (`dsh-client-modules/lib/types/client/manifest.d.ts:9-16`): running the bundle only
 * **registers** the factory; all side effects run at materialization time.
 *
 * v2.3 keeps only two pieces of functionality (the DSH-side viewport panel and blender_rt_pick were removed in v2.3):
 *   ① `@` mention source — `GET /host/scene-items?q=` grouped by object/material/collection;
 *   ② Blender native selection → draft — the headless bridge (`conversation.input.dock`) polls
 *      `GET /host/selection/latest` and inserts the selection pushed by the addon into the current session draft (**never sends automatically**).
 *
 * Discipline:
 *   - No `import`/`export` syntax, no top-level `await`, no references to Node built-in modules;
 *     `require("react")` is allowed (supplied by the baseline; the core client-ui package uses it the same way).
 *   - All fetch failures **degrade silently**; `@` candidate failures return `[]` and **never throw**.
 *   - Selection insertion **never sends automatically**; it only fills the draft.
 *   - Backend address defaults to http://127.0.0.1:9877 and can be overridden by ctx config / localStorage.
 */
window.__ModuleLoader__.load({
  id: 'dsh-blender-plugin',
  factory: (require) => {
    var module = { exports: {} }
    var exports = module.exports
    Object.defineProperty(exports, Symbol.toStringTag, { value: 'Module' })
    var React = require('react')

    //#region configuration
    /** Default backend address (contract §2.4 / AGENTS.md §2: backend 127.0.0.1:9877). */
    var DEFAULT_BACKEND = 'http://127.0.0.1:9877'
    /** localStorage override key (the highest-priority user-side override). */
    var LS_BACKEND_KEY = 'dsh-blender-plugin:backend'
    /** v2.3: Blender native selection poll interval (polled only while a session is visible). */
    var SELECTION_POLL_MS = 100 // v2.6.1 measured in practice: 1200→100ms, end-to-end p50 993→156ms (localhost loopback, see contract "selection polling")
    /** v2.3: max object names listed in the draft text (collapse into a summary with hundreds of parts, don't flood). */
    var SELECTION_DRAFT_NAME_LIMIT = 24
    /** v2.4: max indices/names listed in the draft for sub-elements (vertices/edges/faces/bones). */
    var SUB_DRAFT_INDEX_LIMIT = 12

    /** The address resolved from ctx config during apply(); backend() layers localStorage on top of it. */
    var configuredBackend = DEFAULT_BACKEND
    /** Idempotence guard: cordis applies only once per fiber; reset on dispose (see the effect inside apply). */
    var started = false

    /** Strip trailing slashes (no regex literal, to avoid false hits from the coarse screen). */
    function stripTrailingSlashes(value) {
      var out = String(value === null || value === undefined ? '' : value)
      while (out.length > 0 && out.charAt(out.length - 1) === '/') out = out.slice(0, -1)
      return out
    }

    /**
     * The currently effective backend address. localStorage is re-read on every call, so after the user runs
     * `localStorage.setItem("dsh-blender-plugin:backend", "http://…")` in the console it takes effect immediately.
     */
    function backend() {
      try {
        var v = window.localStorage.getItem(LS_BACKEND_KEY)
        if (v) return stripTrailingSlashes(v)
      } catch (e) {
        /* private mode / no localStorage → fall back to the configured value */
      }
      return configuredBackend
    }

    /** Precedence: window.__DSH_BLENDER_BACKEND__ > ctx.config.{backend,host,blenderBackend} > default. */
    function resolveConfiguredBackend(ctx) {
      try {
        var g = window.__DSH_BLENDER_BACKEND__
        if (typeof g === 'string' && g) return stripTrailingSlashes(g)
      } catch (e) {
        /* ignore */
      }
      try {
        var c = ctx && ctx.config
        if (c) {
          if (typeof c.backend === 'string' && c.backend) return stripTrailingSlashes(c.backend)
          if (typeof c.host === 'string' && c.host) return stripTrailingSlashes(c.host)
          if (typeof c.blenderBackend === 'string' && c.blenderBackend)
            return stripTrailingSlashes(c.blenderBackend)
        }
      } catch (e) {
        /* ignore */
      }
      return DEFAULT_BACKEND
    }
    //#endregion

    //#region small shared helpers
    /** Any value → readable error text (never throws). */
    function errText(e) {
      if (e === null || e === undefined) return 'unknown error'
      if (typeof e === 'string') return e
      if (e.message) return String(e.message)
      return String(e)
    }

    /** Clamp to [0,1] (contract §1.5: out-of-range coordinates are clamped). */
    function clamp01(n) {
      if (!(typeof n === 'number') || n !== n) return 0
      if (n < 0) return 0
      if (n > 1) return 1
      return n
    }

    /** Take the last path segment (the panel shows the .blend file name). */
    function shortPath(p) {
      var s = String(p === null || p === undefined ? '' : p)
      var i = Math.max(s.lastIndexOf('/'), s.lastIndexOf('\\'))
      return i >= 0 ? s.slice(i + 1) : s
    }

    /** Unix seconds → local HH:MM:SS. */
    function timeLabel(unixSec) {
      try {
        var d = new Date(unixSec * 1000)
        function two(n) {
          return n < 10 ? '0' + n : String(n)
        }
        return two(d.getHours()) + ':' + two(d.getMinutes()) + ':' + two(d.getSeconds())
      } catch (e) {
        return ''
      }
    }

    /** source field → label (contract §1.2). */
    function sourceLabel(src) {
      if (src === 'user') return 'user'
      if (src === 'auto') return 'auto'
      if (src === 'model') return 'model'
      return 'none'
    }

    /**
     * Safely fetch a service from ctx: `ctx.get(name)` is cordis's safe accessor
     * (same usage as `dsh-client-ui-conversation/lib/client.js:22945`);
     * it returns undefined instead of throwing when the service is not mounted.
     */
    function serviceOf(ctx, name) {
      try {
        if (ctx && typeof ctx.get === 'function') return ctx.get(name)
        if (ctx) return ctx[name]
      } catch (e) {
        /* ignore */
      }
      return undefined
    }
    //#endregion

    //#region HTTP (all never throw; failures fold into {ok:false})
    /**
     * Never-throwing JSON fetch. Every failure folds into `{ ok:false, status, body:null, error }`
     * and the caller degrades silently — the contract requires the panel to "degrade silently on fetch failure".
     * @returns {Promise<{ok:boolean,status:number,body:any,error:(string|null)}>}
     */
    async function fetchJSON(url, init) {
      var res
      try {
        res = await window.fetch(url, init)
      } catch (e) {
        return { ok: false, status: 0, body: null, error: errText(e) }
      }
      var status = res && typeof res.status === 'number' ? res.status : 0
      var httpOk = !!(res && res.ok)
      var body = null
      try {
        body = await res.json()
      } catch (e) {
        body = null
      }
      return { ok: httpOk, status: status, body: body, error: null }
    }

    /** POST a small JSON body (sets content-type automatically). */
    function postJSON(url, payload) {
      return fetchJSON(url, {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify(payload),
      })
    }

    /**
     * `GET /host/ready` → response body or null (contract §7.1).
     * **The only basis for gating**; anything unreachable/not-ready counts as "unavailable" (silent degradation).
     */
    //#endregion

    //#region click → draft (contract §2.4; **never sends automatically**)
    /**
     * Read the current draft text of the session input box (used by the fallback channel: never overwrites what the user wrote).
     * `SessionInput.state: SnapshotStore<InputState>`, `InputState.draft: string`
     * (`dsh-client-ui-conversation/lib/types/client/contract/input.d.ts:254-260`).
     * @returns {{readable:boolean, draft:string}}
     */
    function readDraftInfo(sessionInput) {
      try {
        var st = sessionInput && sessionInput.state
        if (st && typeof st.getSnapshot === 'function') {
          var snap = st.getSnapshot()
          if (snap && typeof snap.draft === 'string') return { readable: true, draft: snap.draft }
        }
      } catch (e) {
        /* ignore */
      }
      return { readable: false, draft: '' }
    }

    /** notify when available, silent otherwise (contract §2.4 step 5). */
    function notifyInfo(deps, text) {
      try {
        var f = deps && deps.fallbackInput
        if (f && typeof f.notify === 'function') {
          f.notify('info', text)
          return
        }
      } catch (e) {
        /* silent */
      }
    }

    //#endregion

    //#region v2.3 · Blender native selection → DSH draft (contract v2.3 supplement)
    /**
     * Fold the selection payload pushed by the addon into a single draft text.
     * An empty selection (no names) returns null — the caller uses that to skip insertion.
     *
     * Two kinds in v2.3:
     *   · objects    — the objects the user selected; when the list exceeds SELECTION_DRAFT_NAME_LIMIT it collapses into "first N + M total";
     *   · collection — a whole collection the user sent directly (a large assembly); gives the collection name + item count + the first few members.
     */
    /**
     * v2.4: sub-element selection in edit mode / pose mode → draft text.
     * Meshes give vertex/edge/face counts + index samples; armatures give the selected bone names; curves/lattices give control point counts.
     * The complete arrays are in the payload (get_selection can query them too); only the first SUB_DRAFT_INDEX_LIMIT are listed here.
     */
    function subSelectionText(sel) {
      var sub = sel && sel.sub
      if (!sub || typeof sub !== 'object') return null
      var type = String(sub.type || '')
      var obj = String(sub.object || '')
      var counts = sub.counts && typeof sub.counts === 'object' ? sub.counts : {}
      var more = sub.truncated === true
      var prefix = 'Blender sub-element selection'
      if (type === 'MESH') {
        var v = Number(counts.vertices || 0),
          e = Number(counts.edges || 0),
          f = Number(counts.faces || 0)
        var text =
          'Blender edit mode (mesh) "' +
          obj +
          '": selected ' +
          v +
          ' vertices / ' +
          e +
          ' edges / ' +
          f +
          ' faces.'
        var idx = sub.indices && typeof sub.indices === 'object' ? sub.indices : {}
        var labels = { vertices: 'vertex indices', edges: 'edge indices', faces: 'face indices' }
        var parts = []
        for (var k in labels) {
          if (!Object.prototype.hasOwnProperty.call(labels, k)) continue
          var arr = Array.isArray(idx[k]) ? idx[k] : []
          if (!arr.length) continue
          var shown = arr.slice(0, SUB_DRAFT_INDEX_LIMIT).join(',')
          if (arr.length > SUB_DRAFT_INDEX_LIMIT || more) shown += '…'
          parts.push(labels[k] + ': ' + shown)
        }
        if (parts.length) text += parts.join('; ') + '.'
        return text + 'Use bpy / BMesh to modify these elements precisely; when the user says "these vertices/edges/faces" they mean these.'
      }
      if (type === 'ARMATURE') {
        var bones = Array.isArray(sub.bones) ? sub.bones : []
        var boneCount = Number(counts.bones || bones.length)
        var head =
          'Blender armature "' +
          obj +
          '" ' +
          (String(sub.mode || '') === 'POSE' ? 'pose mode' : 'edit mode') +
          ': selected ' +
          boneCount +
          ' bones'
        if (bones.length) {
          head += ': ' + bones.slice(0, SUB_DRAFT_INDEX_LIMIT).join(', ')
          if (bones.length > SUB_DRAFT_INDEX_LIMIT || more) head += '…'
        }
        return (
          head +
          ". Use bpy.data.objects['" +
          obj +
          '\'].pose.bones[...] to address them precisely; when the user says "these bones" they mean these.'
        )
      }
      if (type === 'CURVE' || type === 'LATTICE') {
        var pts = Array.isArray(sub.points) ? sub.points : []
        var pcount = Number(counts.points || pts.length)
        var label = type === 'CURVE' ? 'curve/surface control points' : 'lattice control points'
        var txt =
          'Blender ' +
          label +
          ' "' +
          obj +
          '": ' +
          String(sub.mode || '') +
          ', ' +
          pcount +
          ' selected'
        if (pts.length) {
          var sample = pts.slice(0, SUB_DRAFT_INDEX_LIMIT).map(function (p) {
            return Array.isArray(p) ? String(p[0]) + ':' + String(p[1]) : String(p)
          })
          txt += ': ' + sample.join(', ')
          if (pts.length > SUB_DRAFT_INDEX_LIMIT || more) txt += '…'
        }
        return txt + '. Address the elements by (spline_index, point_index); when the user says "these points" they mean these.'
      }
      if (type === 'OTHER') {
        return (
          'Blender ' +
          String(sub.mode || 'edit mode') +
          ' (object "' +
          obj +
          '"): ' +
          String(sub.note || 'sub-elements are not expanded yet; use Python to read the current selection') +
          '.'
        )
      }
      return null
    }

    function selectionMessageText(payload) {
      var sel = payload && payload.selection ? payload.selection : null
      if (!sel) return null
      var kind = sel.kind === 'collection' ? 'collection' : 'objects'
      var names = Array.isArray(sel.names)
        ? sel.names.filter(function (n) {
            return typeof n === 'string' && n.length > 0
          })
        : []
      var count = typeof sel.count === 'number' ? sel.count : names.length

      if (kind === 'collection') {
        var coll =
          typeof sel.collection === 'string' && sel.collection.length > 0 ? sel.collection : null
        if (!coll) return null
        var shown = names.slice(0, SELECTION_DRAFT_NAME_LIMIT)
        var head = 'Blender collection: ' + coll + ' (' + count + ' items'
        if (shown.length) {
          head += '; first ' + shown.length + ': ' + shown.join(', ')
          if (sel.truncated || count > shown.length || names.length > shown.length) head += '…'
        }
        head +=
          "). Get the members with bpy.data.collections['" +
          coll +
          '\'].objects; when the user says "this collection/this batch" they mean it.'
        return head
      }

      var subText = subSelectionText(sel)
      if (subText) return subText
      if (!names.length) return null
      var drawn = names.slice(0, SELECTION_DRAFT_NAME_LIMIT)
      var text = 'Blender selection: ' + drawn.join(', ')
      if (sel.truncated || count > drawn.length || names.length > drawn.length) {
        text += ' (' + count + ' items total, only the first ' + drawn.length + ' listed)'
      }
      text += '.'
      if (sel.active) text += 'Active object: ' + sel.active + '.'
      if (sel.mode) text += 'Mode: ' + sel.mode + '.'
      if (Array.isArray(sel.collections) && sel.collections.length && count > 1) {
        var summary = sel.collections.slice(0, 4).map(function (c) {
          return String(c.name) + '(' + Number(c.count || 0) + ')'
        })
        text += 'Collections involved: ' + summary.join(', ') + '.'
      }
      return text + 'When the user says "this/these" they mean them; the object names can be used directly in bpy.data.objects.'
    }

    /**
     * Write the selection into the current session draft (**never sends automatically**).
     * Prefers inputActions.insertText (appendable), otherwise falls back to SessionInput.setDraft (only when the draft is empty).
     * @returns {Promise<{ok:boolean, how?:string, reason?:string, text?:string}>}
     */
    async function applySelectionToDraft(deps, payload) {
      var text = selectionMessageText(payload)
      if (!text) return { ok: false, reason: 'no object names to insert (empty selection)' }
      var sessionId = deps && deps.sessionId
      var actions = deps && deps.inputActions
      var fallback = deps && deps.fallbackInput
      if (!sessionId) return { ok: false, reason: 'no sessionId available — cannot write the draft', text: text }
      if (!actions && !fallback)
        return { ok: false, reason: 'no inputActions available — cannot write the draft', text: text }
      if (actions) {
        var wrote = false
        for (var attempt = 0; attempt < 2 && !wrote; attempt++) {
          try {
            wrote = actions.insertText(text, actions.captureInsertion()) === true
          } catch (e) {
            wrote = false
          }
        }
        if (!wrote) return { ok: false, reason: 'text insertion refused (the draft is changing or locked)', text: text }
        notifyInfo(deps, 'Blender selection received (added to draft, not sent)')
        return { ok: true, how: 'actions', text: text }
      }
      // the fallback channel only has setDraft (whole replacement) → write only when "readable and empty", never overwrite user content
      var info = readDraftInfo(fallback)
      if (!info.readable) return { ok: false, reason: 'the fallback channel cannot read the current draft', text: text }
      if (info.draft.length > 0)
        return { ok: false, reason: 'the draft already has content; the fallback channel does not overwrite', text: text }
      try {
        fallback.setDraft(text)
      } catch (e) {
        return { ok: false, reason: 'text write failed: ' + errText(e), text: text }
      }
      notifyInfo(deps, 'Blender selection received (added to draft, not sent)')
      return { ok: true, how: 'fallback', text: text }
    }

    /**
     * Build the headless bridge component for "Blender selection → draft".
     * Registered on `conversation.input.dock` (session scope, permanently mounted, renders null):
     * it keeps receiving the selections pushed by the Blender-side button even while the panel is collapsed.
     */
    function makeSelectionBridge() {
      function BlenderSelectionBridge(props) {
        var p = props || {}
        var sessionId =
          p.sessionId !== undefined && p.sessionId !== null ? p.sessionId : p.blenderSessionId
        var inputActions = p.inputActions || null
        var fallbackInput = p.blenderInput || null
        var lastSeqRef = React.useRef(0)
        var busyRef = React.useRef(false)
        var failCountRef = React.useRef(0)
        var sessionRef = React.useRef(sessionId)
        var actionsRef = React.useRef(inputActions)
        var fallbackRef = React.useRef(fallbackInput)
        sessionRef.current = sessionId
        actionsRef.current = inputActions
        fallbackRef.current = fallbackInput

        React.useEffect(function () {
          var alive = true
          var timer = 0
          function schedule() {
            if (!alive) return
            timer = window.setTimeout(tick, SELECTION_POLL_MS)
          }
          async function tick() {
            try {
              // Do not skip based on page visibility: the user may have clicked the button in Blender with the DSH tab in the background;
              // the selection should still reach the draft (otherwise they come back to DSH and find nothing arrived). The poll itself is cheap (zero Blender round-trips).
              if (busyRef.current || !sessionRef.current) {
                schedule()
                return
              }
              var res = await fetchJSON(backend() + '/host/selection/latest', { cache: 'no-store' })
              var body = res && res.body
              if (alive && body && body.ok === true && body.unconsumed === true && body.selection) {
                var seq = Number(body.seq) || 0
                if (seq > lastSeqRef.current) {
                  lastSeqRef.current = seq
                  busyRef.current = true
                  var out = { ok: false, reason: 'bridge_error' }
                  try {
                    out = await applySelectionToDraft(
                      {
                        sessionId: sessionRef.current,
                        inputActions: actionsRef.current,
                        fallbackInput: fallbackRef.current,
                      },
                      { selection: body.selection },
                    )
                  } catch (e) {
                    out = { ok: false, reason: 'bridge_exception:' + errText(e) }
                  }
                  if (out.ok === true) {
                    failCountRef.current = 0
                    try {
                      var consumedOk = await postJSON(backend() + '/host/selection/consume', {
                        seq: seq,
                        ok: true,
                        how: out.how || 'actions',
                      })
                      void consumedOk
                    } catch (e) {
                      /* local lastSeq already blocks duplicate insertion; consume on the next pass */
                    }
                    busyRef.current = false
                  } else {
                    // Insertion failed: **do not consume**, retry on the next tick (session/draft locks usually recover within a few hundred ms).
                    // Only after 3 consecutive failures consume it and record the reason in the receipt, to avoid unbounded retries.
                    failCountRef.current += 1
                    if (failCountRef.current === 1) {
                      notifyInfo(
                        { fallbackInput: fallbackRef.current },
                        'Blender selection not written to the draft: ' + String(out.reason || 'unknown'),
                      )
                    }
                    if (failCountRef.current >= 3) {
                      try {
                        var consumedFail = await postJSON(backend() + '/host/selection/consume', {
                          seq: seq,
                          ok: false,
                          reason: String(out.reason || 'unknown'),
                        })
                        void consumedFail
                      } catch (e) {
                        /* ignore */
                      }
                      failCountRef.current = 0
                    } else {
                      lastSeqRef.current = seq - 1 // allow the next tick to retry the same seq
                    }
                    busyRef.current = false
                  }
                }
              }
            } catch (e) {
              /* silent: the bridge must not affect the session */
            }
            schedule()
          }
          tick()
          return function () {
            alive = false
            if (timer) window.clearTimeout(timer)
          }
        }, [])
        return null
      }
      return BlenderSelectionBridge
    }
    //#endregion

    //#region @ mention source (contract §2.5)
    /** ref prefix → allowed kinds (`object:<name>` / `material:<name>` / `collection:<name>`). */
    var REF_KINDS = { object: true, material: true, collection: true }

    /**
     * Split a ref: `object:Cube` → `{kind:"object", name:"Cube"}`; bare `Cube` → `{kind:"object", name:"Cube"}`.
     * A bare value is treated as object ⇒ the two codec forms in contract §2.5 (`'@'+ref`, `'<blender-object>'+ref+'</blender-object>'`)
     * hold **verbatim** for a bare ref, while a prefixed ref yields more accurate model text.
     */
    function splitRef(ref) {
      var s = String(ref === null || ref === undefined ? '' : ref)
      var i = s.indexOf(':')
      if (i > 0) {
        var kind = s.slice(0, i)
        if (REF_KINDS[kind] === true) return { kind: kind, name: s.slice(i + 1) }
      }
      return { kind: 'object', name: s }
    }

    /**
     * `@` candidate data source: `GET /host/scene-items?q=<query>`.
     * Grouped by object / material / collection via `section` (candidates have **no** thumbnail field, contract §2.5).
     * **On failure it must return `[]` and not throw** — throwing would pollute the input box.
     */
    async function sceneItemCandidates(req) {
      try {
        var q = req && typeof req.query === 'string' ? req.query : ''
        var r = await fetchJSON(backend() + '/host/scene-items?q=' + encodeURIComponent(q))
        if (!r.ok || !r.body || r.body.ok !== true) return []
        var out = []
        // [response field, section name, ref prefix, icon]
        var groups = [
          ['objects', 'Objects', 'object', 'file'],
          ['materials', 'Materials', 'material', 'file'],
          ['collections', 'Collections', 'collection', 'folder'],
        ]
        for (var g = 0; g < groups.length; g++) {
          var list = r.body[groups[g][0]]
          if (!list || typeof list.length !== 'number') continue
          for (var i = 0; i < list.length; i++) {
            var it = list[i]
            if (!it || !it.name) continue
            var name = String(it.name)
            out.push({
              name: name,
              label: name,
              description: groups[g][0] === 'objects' ? String(it.type || 'OBJECT') : groups[g][1],
              icon: groups[g][3],
              section: groups[g][1],
              value: groups[g][2] + ':' + name,
            })
          }
        }
        return out
      } catch (e) {
        return []
      }
    }

    /** Pick one candidate → ReferenceInsert (contract §2.5). */
    function onPickItem(pick) {
      var c = pick && pick.candidate ? pick.candidate : {}
      var ref = typeof c.value === 'string' && c.value ? c.value : String(c.name || '')
      var parts = splitRef(ref)
      return {
        insert: {
          source: 'blender',
          ref: ref,
          label: parts.name,
          appearance: 'file',
          clipboardText: '@' + parts.name,
        },
      }
    }

    /** ref ↔ text/clipboard projection (contract §2.5; `serialize` is the official "@mention → model text" channel). */
    var blenderCodec = {
      clipboardText: function (ref) {
        return '@' + splitRef(ref).name
      },
      serialize: function (ref) {
        var parts = splitRef(ref)
        return Promise.resolve(
          '<blender-' + parts.kind + '>' + parts.name + '</blender-' + parts.kind + '>',
        )
      },
    }
    //#endregion

    //#region plugin entry
    /**
     * Fallback channel: look up the session-scoped ctx from the `sessionId` resolved by the framework,
     * then take that session's `SessionInput` (has `setDraft`/`addAttachments`/`notify`).
     *
     * Source (local runtime): the same QueueDock usage as
     * `dsh-client-ui-conversation/lib/client.js:20515-20522` — `const actx = ctx.sessions.scope(sessionId)` →
     * `actx.get("conversation")` → `conversation.input.for(actx)`.
     * `ctx.sessions.scope(id)` signature:
     * `dsh-api-session-controller/lib/types/client/sessions/service.d.ts:212`.
     */
    function sessionFallback(ctx, sessionId) {
      var out = { blenderSessionId: sessionId, blenderInput: null }
      try {
        var sessions = serviceOf(ctx, 'sessions')
        var actx =
          sessions && typeof sessions.scope === 'function' ? sessions.scope(sessionId) : undefined
        if (actx && typeof actx.get === 'function') {
          var conversation = actx.get('conversation')
          if (conversation && conversation.input && typeof conversation.input.for === 'function') {
            out.blenderInput = conversation.input.for(actx)
          }
        }
      } catch (e) {
        out.blenderInput = null
      }
      return out
    }

    /**
     * cordis plugin entry. Injects only `slots` (required by the panel, and the form verified locally with coc-dice);
     * `inputTriggers` is awaited lazily via `ctx.inject([...])`, so that "input trigger not mounted ⇒ the panel vanishes too" cannot happen.
     */
    /**
     * cordis plugin entry. Injects only `slots`; `inputTriggers` is awaited lazily via `ctx.inject([...])`,
     * so that "input trigger not mounted ⇒ the native selection bridge vanishes too" cannot happen.
     * v2.3: the DSH-side viewport panel and blender_rt_pick were removed; only the @ mention source + native selection bridge remain here.
     */
    function apply(ctx) {
      if (started) return
      started = true
      configuredBackend = resolveConfiguredBackend(ctx)

      var SelectionBridge = makeSelectionBridge()

      // ① @ mention source (contract §2.5). inputTriggers service name, see
      //    dsh-client-ui-input-trigger/lib/client.js:1526
      ctx.inject(['inputTriggers'], function (scope) {
        var triggers = typeof scope.get === 'function' ? scope.get('inputTriggers') : undefined
        if (!triggers || typeof triggers.registerSource !== 'function') return
        scope.effect(function () {
          return triggers.registerSource({
            trigger: '@',
            name: 'blender',
            candidates: function (session, req) {
              return sceneItemCandidates(req)
            },
            onPick: onPickItem,
            codec: blenderCodec,
          })
        }, 'dsh-blender-plugin: @ blender scene items')
      })

      // ② v2.3: Blender native selection → the current session draft (headless dock; renders no UI)
      ctx.slots.inject('conversation.input.dock', function () {
        return ctx.slots.register(
          {
            name: 'conversation.input.dock',
            id: 'blender-selection-bridge',
            order: 90,
            inject: function (sessionId) {
              return sessionFallback(ctx, sessionId)
            },
          },
          SelectionBridge,
        )
      })

      // ③ reset the guard on dispose (to make hot reload / re-applying possible)
      ctx.effect(function () {
        return function () {
          started = false
        }
      }, 'dsh-blender-plugin: reset apply guard')
    }

    var inject = ['slots']

    exports.apply = apply
    exports.inject = inject
    // only for offline self-checks/probes asserting the pure functions (DSH reads only apply/inject; unknown exports have no side effects)
    exports.__selftest = {
      DEFAULT_BACKEND: DEFAULT_BACKEND,
      LS_BACKEND_KEY: LS_BACKEND_KEY,
      splitRef: splitRef,
      onPickItem: onPickItem,
      blenderCodec: blenderCodec,
      sceneItemCandidates: sceneItemCandidates,
      stripTrailingSlashes: stripTrailingSlashes,
      // v2.3 (Blender native selection → DSH)
      SELECTION_POLL_MS: SELECTION_POLL_MS,
      SELECTION_DRAFT_NAME_LIMIT: SELECTION_DRAFT_NAME_LIMIT,
      SUB_DRAFT_INDEX_LIMIT: SUB_DRAFT_INDEX_LIMIT,
      selectionMessageText: selectionMessageText,
      subSelectionText: subSelectionText,
      applySelectionToDraft: applySelectionToDraft,
      makeSelectionBridge: makeSelectionBridge,
    }
    return module.exports
  },
})
