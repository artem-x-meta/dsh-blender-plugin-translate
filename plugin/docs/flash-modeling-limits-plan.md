# flash modeling ceiling: three-way integration plan — gate · humanoid and face · visual perception

> Conclusion first: **the ceiling = the surface coverage of external pathways**, not model capability.
> The three classes of problems flash (deepseek-v4.1-flash) exposes in this project — the gate cannot be relied on, humanoids and faces come out badly, and reference images cannot be read clearly —
> are three facets of **one and the same root cause**: **in every step that needs "an eye / professional experience / subjective judgment", it is unreliable**.
> The only effective direction for raising the ceiling: **replace those steps with externally computable pathways; the model only orchestrates and reads numbers.**

## 0. Unified diagnosis

| Step | How flash falls short | Evidence measured in practice in this project |
|---|---|---|
| **Acceptance (gate)** | It says "looks fine"; criteria are unsystematic | 68% of the 111 failures are timeouts; 5 long-tail new families were **really used 0 times** ("won't use what I'm not familiar with") |
| **Creation (humanoid/face)** | Anatomy/proportion/topology is professional knowledge; point-by-point control is not achievable | In one 95-object assembly, `sculpt_*` was **never called once** (wrong shape class + topology edits are not recomputable) |
| **Observation (vision)** | Resolution is downsampled first; counting and small-object recognition are inherently weak | On site `rt_see` caught 5 shape defects, but detail-class criteria still need a human to supply numbers |

Unified formula:

```
Reliable output = what the model can do stably (orchestrate / fill parameters / read numbers)
                + what external pathways can cover (measurement / geometry / rules / assets)
```

flash's shortcomings **all fall in the second term** — so the move is not "make it stronger" but **make the second term bigger**.

## 1. Target pipeline (every step produces numbers, and there are at least two independent pathways)

```
Reference image/drawing ──► [measurement · OCR · direct vector read] ──► spec.py (numbers, frozen)
                                          │
                                          ▼
                    [parametric generation / asset base + landmark fitting]
                                          │
                                          ▼
                     [geometry gate] audit/fix/print  ─┐
                     [asset gate] glTF-Validator       ├─► verdict (three-state, the script gives the conclusion)
                     [proportion gate] head/human ratios ─┘
                                          │
                                          ▼
                        render ──► [diff · IoU · landmark error] ──► numeric feedback
```

**Hard rule**: when any step has only one pathway, the ceiling is that pathway's blind spot (the "exactly touching parts misreported as floaters" measured this round is exactly a single-pathway blind spot).

## 2. Final list of measures

### Immediate · deliverable the same day (zero external dependencies)

| # | Measure | What it does | Acceptance criterion |
|---|---|---|---|
| 1 | **Gate calibration suite** | Deliberately inject 8 classes of defects (translation out of tolerance / deleted rivets / broken manifold / flipped normals / thin wall / self-intersection / floater / duplicates), and assert "every class is caught by some gate" | **Defect capture rate** (target ≥7/8); anything not caught is immediately exposed as a gate still to be added |
| 2 | **Perception toolkit of four** | `img_scan` (contour/bbox/aspect ratio/main-axis angle/line angles/sample color) · `img_crop` (ROI crop + upsample) · `img_annotate` (draw coordinates and proportion lines back onto the image) · `img_diff` (contour diff + heatmap + IoU) | On the same reference image: **error comparison** between "ask the model directly" and "`img_scan` produces numbers" |
| 3 | **Proportion gate + numeric recipe** | `head_proportions` / `human_proportions` (eye-line position, five-eye width, three facial thirds, head-to-body ratio, shoulder width…) into the gate spec; add two sections to the skill for "face/humanoid", stating **free-form sculpting is forbidden** | Proportion out-of-tolerance is caught by `pass_if`; the recipe is reproducible |
| 4 | **Perception protocol (skill layer)** | ① Looking at an image must produce spec.py numbers, otherwise it counts as not looking; ② at most 2 images per call and each with an explicit question (yes/no or a number); ③ each image carries a pixel↔millimeter scale; ④ later rounds consume only numbers | Skill review passes; later tasks no longer re-read images |

### Short term · 1–3 days (few external dependencies)

| # | Measure | Dependency | Benefit |
|---|---|---|---|
| 5 | **Reference image → landmark → fitting** | MediaPipe Face Mesh / EMOCA / MPFB2 | Recognizability comes from landmarks **computed** from the reference image; the model never touches vertices |
| 6 | **Asset gate**: `deliver_verify` wired to glTF-Validator | node / CLI | "Can the deliverable be parsed downstream" becomes a rule-code gate |
| 7 | **Second self-intersection pathway**: Open3D or pymeshlab re-checks self-intersection/watertightness | pip (separate process, not stuffed into Blender) | Two pathways disagreeing = one of them has a blind spot |
| 8 | **face eval harness** | none | Gives three baseline numbers — **landmark error / head contour IoU / first-pass rate** — so that improvement has a reference |

### On demand · when the spec is complex or CAD-level precision is required

| # | Measure | When it is worth it |
|---|---|---|
| 9 | OCCT (pythonocc): `BRepCheck_Analyzer` / `BRepExtrema_DistShapeShape` / `BRepAlgoAPI_Common` | When ±3 mm tolerance and interpenetration volume must be "computed" rather than "approximated from the mesh" |
| 10 | manifold3d: constructive boolean | When you want invalid geometry to be **impossible to produce** rather than fixed afterwards |
| 11 | OCR (tesseract/PaddleOCR) · direct DXF/STEP read (ezdxf/OCCT) | Largest payoff when the reference is an **engineering drawing/drawing set**: numbers are exact and vision is bypassed entirely |
| 12 | Policy language upgrade (Rego / CUE / JSON Schema) | When the gate spec is complex enough to need reuse/inheritance/versioning |
| 13 | inspect_ai: evaluate a **verifier agent** | When the verifier starts carrying subjective gates, answering "does it actually catch things" |

## 3. Explicitly not doing (none of these solves the root cause)

1. Giving flash more sculpt brushes / finer prompts — making it **hand-write face vertices** is structurally impossible;
2. Hoping "give it a higher-resolution image" helps — the vision encoder downsamples first, so small details are lost at the encoding stage;
3. Replacing "changing the pathway" with "changing the agent" — the value of an independent verifier subagent is a **fresh perspective**, not **finer observation** (already measured in the token-saving round: the gate call itself is cheap; what is expensive is repeatedly loading context).

## 4. One-week landing route

| Day | What to do | Acceptance that day |
|---|---|---|
| Day 1 | Gate calibration suite + perception toolkit of four | Defect capture rate report + reference-image error comparison table |
| Day 2 | Proportion gate (head/human) + two skill sections (including the hard rule forbidding free-form sculpting) | Proportion out-of-tolerance is caught by the gate; the recipe runs end to end |
| Day 3 | face eval harness (get the baseline) | landmark error / contour IoU / first-pass rate |
| Days 4–5 | Fitting path (MPFB2 base or MediaPipe/EMOCA landmarks) | The three face eval numbers vs the Day 3 baseline |
| Days 6–7 | Asset gate (glTF-Validator) + second self-intersection pathway (Open3D/pymeshlab) | Deliverable passes the rule-code gate; two-pathway consistency report |

## 5. In one sentence

> **Do not train the model's eyes and hands; give them external gauges, molds and acceptance criteria.**
> The model orchestrates, fills parameters and reads numbers; measurement, geometry, rules and assets go to external pathways — that is flash's ceiling in this project.
