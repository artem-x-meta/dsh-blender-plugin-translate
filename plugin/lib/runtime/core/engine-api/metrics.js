export function metricsView(E) {
    const metrics = E.metrics;
    return { ...metrics, lastCmdAgeMs: metrics.lastCmdAt ? Date.now() - metrics.lastCmdAt : null };
}
export function createMetricsApi(E) {
    const { metrics } = E;
    return {
        metrics() {
            return { ...metrics, lastCmdAgeMs: metrics.lastCmdAt ? Date.now() - metrics.lastCmdAt : null };
        },
        /** addon protocol actually used by the channel (explicit config or auto-detected result) */
    };
}
//# sourceMappingURL=metrics.js.map