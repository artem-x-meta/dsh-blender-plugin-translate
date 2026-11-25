// Persistent kernel module entry: bootstrap constants + injection/ensure chain
export { KERNEL_BOOTSTRAP } from './bootstrap.js';
import { createKernelInternals } from './api.js';
export function createKernel(E) {
    return createKernelInternals(E);
}
//# sourceMappingURL=index.js.map