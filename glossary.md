# Chinese → English glossary for the DSH Blender toolchain

The plugin's docs are a Russian/Chinese hybrid, and **tool receipts come back with Chinese field
values** (e.g. `"浮块"`, `"真贴上"`). This table is the fixed translation I use when reporting, so
nothing in an answer is ever left in Chinese.

Source of truth: `skills/blender-modeling/*` and `lib/runtime/*` of `dsh-blender-plugin` v3.0.6.

## 1. Verdicts, gates, evidence

| Chinese | English | Where it shows up |
|---|---|---|
| 回执 | receipt | the JSON envelope every plan op returns |
| 判据 | criterion | `note:` field explaining what makes pass/fail |
| 三态 | three-state | verdict is `pass` / `fail` / `degraded` |
| 门 | gate | acceptance gate (`audit_gate`, `gate_run`, `asm_gate`) |
| 验收门 | acceptance gate | same |
| 验收 | acceptance check | |
| 通过 | pass | verdict value |
| 不假通过 | no false pass | degraded never counts as pass |
| 未查完 | not fully checked | cause of `degraded` |
| 补查 | re-check / supplement the check | what to do on `degraded` |
| 门不过 | gate not passed | blocks delivery/merge export |
| 实测 | measured in practice | claims backed by a run, not theory |
| 当前版本 | current version | |
| 未实现 | not implemented | op exists but refuses (`ok:false`) |
| 静默失败 | silent failure | setter that does not apply — must read back |
| 缺陷注入 | defect injection | `eval_run` synthesized-defect suite |
| 反模式 | anti-pattern | |
| 深水参考 | deep-dive reference | pointer to `references/*.md` |

## 2. Geometry, mesh health

| Chinese | English | Notes |
|---|---|---|
| 视图 | view | front/side/top/iso |
| 视口 | viewport | |
| 尺寸 | dimensions | |
| 单位 | units | mm / m / BU |
| 对象 | object | |
| 基本体 | primitive | box / cylinder / cone… |
| 白模 | blockout | low-poly gray model |
| 网格 | mesh | |
| 法线 | normals | |
| 开边 | boundary (open) edges | `boundary_edges` |
| 非流形 | non-manifold | `nonmanifold_edges` |
| 自交 | self-intersection | |
| 松散边 | loose edges | |
| 退化面 | degenerate faces | |
| 内部面 | interior faces | buried faces |
| 收尖 | taper to a point | |
| 浮块 | **floater** | a part that hangs in the air |
| 浮空 | floating | |
| 贴而未焊 | touching but not welded | reports as multiple components |
| 真贴上 | really touching | `mesh_confirmed: true` note |
| 网格复核 | mesh check | |
| 穿模 | **interpenetration** | real clash |
| 隐藏交叠 | **hidden overlap** | intentional, by spec |
| 互差 | mutual deviation | |
| 逐壳 | per connected shell | `normals_shells[]` |
| 有符号体积 | signed volume | negative = normals point inward |
| 包络 | envelope | `audit_gate` bbox gate |
| 装配 | assembly | |
| 拼件接缝 | part seams | |
| 修改器栈 | modifier stack | |
| 细分 | subdivision | |
| 倒角 | bevel | |
| 支撑边 | support edge | keeps bevels sharp under SubSurf |
| 布尔 | boolean | |
| 材质 | material | |
| 曲面 | surface | |
| 放样 | loft | `surface_loft` |
| 扫掠 | sweep | `surface_sweep` |
| 补片 | patch | `surface_patch` |
| 截面 | section | |
| 曲率 | curvature | |
| 厚度 | thickness | |
| 轮廓反推 | contour fitting | `shapesolve_solve` |

## 3. Reference images & measurement

| Chinese | English | Notes |
|---|---|---|
| 参考图 | reference image | |
| 还原 | reconstruction | |
| 标定 | calibration | px_per_mm |
| 单应 | homography | |
| 取点 | picking points | |
| 误差 | error | |
| 自证 | self-verification | |

## 4. Rendering, animation, long jobs

| Chinese | English | Notes |
|---|---|---|
| 取景 | framing | |
| 贴边 | touching the frame edge | worst NDC ≈ 1.0 |
| 留白 | margin | |
| 视内残差 | in-view residual | |
| 采样 | samples | |
| 帧 | frame | |
| 逐帧投影自检 | per-frame projection self-check | |
| 爆炸图 | exploded view | |
| 分解动画 | disassembly animation | |
| 长活 | long-running job | |
| 续跑 | resume / continue | exists-and-skip |
| 光流插值 | optical-flow interpolation | |
| 渲染耗时 | render cost | |

## 5. Workflow & process

| Chinese | English | Notes |
|---|---|---|
| 架构优先 | architecture-first | plugin ops before hand-written bpy |
| 配方 | recipe | |
| 先查目录 | check the catalog first | `blender_rt_plan(op="catalog")` |
| 写租约 | write lease | `blender_viewport(op="lease")` |
| 同机位 | same camera position | required for visual QC |
| 同机位像不像 | does it look like the reference from the same camera | |
| 目标 | target / goal | |
| 默认 | default | |
| 优先 | preferred | |
| 主线程 | main thread | |
| 无头 | headless | |
| 热会话 | hot session (persistent worker) | |
| 冷启动 | cold start | |
| 预算 | budget | |
| 阈值 | threshold | |

## 6. How I report from now on

- Chat answers: Russian.
- Tool, op and field names: kept as-is (they are already Latin: `blender_rt_do`, `audit_mesh`, `verdict`).
- Chinese values inside receipts: translated with the table above, original value quoted only when the exact
  string matters (and then with the English gloss next to it).
