import { EXT_ROUTES } from './routes.generated.js';
import { handleRoute, hit, miss, routeMatches } from './plan-call.js';
/** The EXT table matches in config/routing.json order: 21 module prefixes → gui_ → render_ → contract fallback. */
export async function routeExtRouting(E, o, payload) {
    for (const route of EXT_ROUTES) {
        if (!routeMatches(route, o))
            continue;
        return hit(handleRoute(E, route, o, payload));
    }
    return miss();
}
//# sourceMappingURL=ext-routing.js.map