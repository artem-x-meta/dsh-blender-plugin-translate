# Chair backrest joint: external evidence insufficient + probe discrimination (auto-generated)

> Phase one (external evidence only): **external evidence insufficient (both attach and insert are satisfiable) → must report unresolved**

> Phase two (with probe evidence): **after the probe only one is supported: insert**

| Hypothesis | Allowed range | Tried | Best board parameters | External error (side+rear) | Probe reading | Difference from ground truth | External verdict | Probe verdict |
|---|---|---|---|---|---|---|---|---|
| attach | dy 0.0~0.03 · tilt -2.0~6.0 deg · dz -0.02~0.02 · tenon length 0.0~0.0 | 48 | dy=0.010 tilt=-2.0 dz=0.020 tenon=0.000 | 184 | 0.0000 m | 0.0600 m | unresolved | refuted |
| insert | dy 0.0~0.03 · tilt -2.0~6.0 deg · dz -0.02~0.02 · tenon length 0.03~0.1 | 48 | dy=0.010 tilt=-2.0 dz=0.020 tenon=0.030 | 184 | 0.0650 m | 0.0050 m | unresolved | supported |

## Identifiability (which parameters can be pinned when using external evidence only)

| Hypothesis | Parameter | Minimum external error at each value of that parameter | Range | Identifiable? |
|---|---|---|---|---|
| attach | dy | 0.0:476 / 0.01:184 / 0.02:485 / 0.03:974 | 790 | yes |
| attach | tilt | -2.0:184 / 6.0:495 | 311 | yes |
| attach | dz | -0.02:186 / 0.02:184 | 2 | no (flat) |
| attach | tenon_len | 0.0:184 | 0 | no (flat) |
| insert | dy | 0.0:476 / 0.01:184 / 0.02:485 / 0.03:974 | 790 | yes |
| insert | tilt | -2.0:184 / 6.0:495 | 311 | yes |
| insert | dz | -0.02:186 / 0.02:184 | 2 | no (flat) |
| insert | tenon_len | 0.03:184 / 0.065:184 / 0.1:184 | 0 | no (flat) |

> A range ≈ 0 means the dimension is **not identifiable** against external evidence: the program must say so rather than casually picking a value (in this example it is tenon_len).

## Basis for the verdict (two plain sentences)

- **attach**: external — external evidence is satisfiable (best=184 <= 220), but tenon_len is not identifiable in the external view → a probe is needed; probe — the probe (disassembly + depth gauge): reading 0.0000 m, differs from the ground truth 0.0600 m by 0.0600 m > 0.0100 m
- **insert**: external — external evidence is satisfiable (best=184 <= 220), but tenon_len is not identifiable in the external view → a probe is needed; probe — the probe (disassembly + depth gauge): reading 0.0650 m, differs from the ground truth 0.0600 m by 0.0050 m <= 0.0100 m

## Evidence files

| File | Content |
|---|---|
| gt_external_side.png / gt_external_rear.png | the two external ground-truth images (the joint is hidden by the baffle) |
| gt_probe_no_seat.png | probe evidence: the tenon area after hiding the seat |
| best_attach_probe.png | the attach hypothesis' best parameters in the probe view |
| best_insert_probe.png | the insert hypothesis' best parameters in the probe view |

## Reproduction

    blender -b --factory-startup --python docs/examples/chair-backrest/run.py -- <outdir>
    # or blender_rt_headless(preload='view', script=..., outdir=...)

## How to use the conclusion

- when external evidence is insufficient, do not casually choose between attach / insert: report unresolved and list "which probes are needed";
- before discrimination, boolean_union / weld / apply_transform are forbidden (they destroy reversibility);
- after the probe evidence is in, judge supported / refuted, and archive the evidence of both judgments together.
