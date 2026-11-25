// Blender real-time interaction backend — process entry point.
// Behaviour frozen: 29 routes, write lease, CORS, lifecycle identical to before the split; the implementation lives in http/.
import http from 'node:http';
import { createEngine, engineProvenance } from './engine.js';
import { createSelectionStore } from './selectionstore.js';
import { describeConfig } from './config.js';
import { PORT, HOST, stats, pushRtt, rttView, reqCounts, bump } from './http/config.js';
import { json, streamJson, readBody, hostJson, hostErrText } from './http/response.js';
import { LEASE, leaseView, releaseStaleLease, leaseAcquire, leaseGate, isReadOnly, } from './http/lease.js';
import { trimJob, clampIntParam } from './http/jobs.js';
import { createRouter } from './http/router.js';
import { createRoutes, CONTRACT_ROUTES } from './http/routes/index.js';
import { startServer } from './http/lifecycle.js';
import { errorMessage } from './core/json.js';
const engine = createEngine();
// v2.3: Blender's native selection event (N-panel "send selection to DSH" → here → the client inserts a draft)
const selectionStore = createSelectionStore();
const E = {
    engine,
    selectionStore,
    PORT,
    HOST,
    stats,
    json,
    streamJson,
    readBody,
    pushRtt,
    rttView,
    reqCounts,
    bump,
    LEASE,
    leaseView,
    releaseStaleLease,
    leaseAcquire,
    leaseGate,
    isReadOnly,
    trimJob,
    clampIntParam,
    describeConfig,
    engineProvenance,
    hostJson,
    hostErrText,
};
const routes = createRoutes(E);
const server = http.createServer(createRouter({ HOST, PORT, bump, routes }));
// Blender may not be running / may not have the addon enabled — that must not take the whole backend down: a failed start just logs one line and errors are reported per call.
try {
    await engine.start();
}
catch (e) {
    console.error('[blender-rt] could not reach the addon at startup (Blender not running or the addon not listening on 9876): ' + errorMessage(e));
}
startServer({ server, engine, port: PORT, host: HOST, routes: CONTRACT_ROUTES });
//# sourceMappingURL=server.js.map