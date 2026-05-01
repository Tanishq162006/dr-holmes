# Eval summary: Dr. Park ablation (n=20, DDXPlus, seed=42)

> ⚠ Honest read: **n=20 is too small to be statistically conclusive.** All
> 95% CIs overlap heavily across runs. Treat the differences below as
> directional, not definitive. A standard-tier run (n=200) is needed to
> commit to any of these readings.

## What we tested

Whether adding **Dr. Chi Park** (primary care, anti-zebra, "common things
are common") to the 6-agent team improves diagnostic accuracy on DDXPlus.
Ran four configurations on the same 20 cases (seed=42, proportional
stratified sampling):

| Run | Park config | Authority |
|---|---|---|
| `baseline_pre_park_n20` | absent (6 agents) | — |
| `with_park_n20` (v1) | gpt-4o-mini | threshold 0.70, weight 1.30× |
| `with_park_v2_n20` | gpt-4o | threshold 0.85, weight 1.15× |
| `with_park_v3_no_authority_n20` | gpt-4o | **disabled** (1.0×) |

"Authority" = when Park's confidence ≥ threshold, her noisy-OR probability
weight gets multiplied and her vote counts double in the cross-specialist
agreement check. Designed to anchor the team toward common dx when she's
clearly confident; in practice, amplified her wrong answers too.

## Headline numbers

| Metric | Pre-Park | v1 (mini, 0.70/1.30) | v2 (4o, 0.85/1.15) | v3 (4o, no auth) |
|---|---|---|---|---|
| **Cases done** | 20/20 | 17/20 ⚠ | 20/20 | 20/20 |
| **Top-1** | **35.0%** | 29.4% | 25.0% | 30.0% |
| Top-3 | 35.0% | 35.3% | 40.0% | 35.0% |
| Top-5 | 50.0% | 41.2% | 40.0% | 45.0% |
| MRR | 0.383 | 0.328 | 0.325 | 0.348 |
| **ECE** | **0.170** | 0.374 | 0.345 | **0.264** |
| Brier | 0.234 | 0.316 | 0.295 | 0.238 |
| Hallucinated | 65% | 55% | 60% | 65% |
| Premature converge | 0% | 5% | 15% | 5% |
| Schema failure | 0% | **15%** ❌ | 0% ✅ | 0% ✅ |
| Cost/case | $0.032 | $0.034 | $0.040 | $0.040 |
| 95% CI on Top-1 | [15–55] | [12–53] | [10–45] | [10–55] |

## What each run taught us

### v1 — gpt-4o-mini for Park, full authority (0.70 / 1.30×)
**Park hurt headline + introduced schema failures.** Strict json_schema on
gpt-4o-mini failed 15% of the time, dropping us to 17/20 cases. ECE more
than doubled (0.17 → 0.37) — Park's wrong-but-confident answers got
amplified by the 1.30× multiplier and her vote-doubling, and the team
prematurely converged on her pick.

**Lesson:** the model has to handle strict structured output reliably
*before* you let it weight votes.

### v2 — gpt-4o for Park, dialed-back authority (0.85 / 1.15×)
**Schema failures disappeared (15% → 0%), but Top-1 still degraded
(35% → 25%) and a new failure mode appeared: 15% premature convergence.**
ECE improved slightly over v1 (0.374 → 0.345) but still 2× worse than
baseline. The tighter threshold + smaller multiplier weren't enough — Park's
authority was still pulling the team into wrong answers when she was
confident on common-but-wrong dx.

**Lesson:** even a small probability multiplier on a confident-but-wrong
voice cascades through noisy-OR aggregation. The fix wasn't tuning, it was
removal.

### v3 — gpt-4o for Park, authority disabled
**Best-recovered with-Park config.** Top-1 came back to 30% (vs baseline
35%), MRR essentially matched baseline (0.348 vs 0.383), ECE recovered to
0.264 (vs baseline 0.170 — still slightly worse, but no longer a disaster).
Premature convergence dropped back to 5%.

**Lesson:** Park's *prompt persona* (anti-zebra, "common things are common")
neither helped nor hurt vs baseline within the CI of n=20. The team
benefited from her common-bias voice in the discussion but didn't need her
vote weighted.

## What this means for the design

1. **Park stays in the lineup** with a normal-weight vote and her primary-care
   prompt persona. She doesn't measurably help at n=20, but she doesn't hurt
   either, and her presence diversifies the team's reasoning style.
2. **`PARK_AUTHORITY_THRESHOLD = 1.01`, `WEIGHT = 1.0` (disabled).** The
   constants stay in `dr_holmes/orchestration/constants.py` so a future
   eval could re-enable them with new parameters — but the n=20 evidence
   says don't.
3. **Park requires gpt-4o, not gpt-4o-mini.** Strict json_schema reliability
   is non-negotiable when an agent participates in vote aggregation.

## Caveats — why these conclusions are tentative

1. **n=20 is tiny.** With 95% CIs of ~[15–55] on Top-1, we cannot
   distinguish 35% from 25% from 30% with any statistical confidence.
2. **All four runs share seed=42, same 20 cases.** Different cases → different
   outcomes. The DDXPlus cases hit some categories where Park *should*
   shine (Pneumonia, Viral pharyngitis, Acute otitis media, Acute laryngitis)
   but those landed 0/1 or 0/2 across every run, suggesting the failure mode
   is upstream of Park's voice — likely Caddick's synthesis or the team's
   collective hallucination on infectious dx.
3. **No statistical significance test** between conditions (paired
   bootstrap deferred to Phase 7.5).
4. **Convergence rate = 0% across all runs** — the team is hitting MAX_ROUNDS
   without satisfying the four convergence criteria. This is its own bug
   worth investigating separately.

## Recommended next eval

A standard-tier run (`--tier standard`, n=200, ~$40–50 budget) comparing
just two conditions:
- `baseline_pre_park` (6 agents)
- `with_park_no_authority` (7 agents, v3 config)

That's enough sample size to actually detect a 5pp Top-1 difference with
95% confidence and either commit to Park or remove her.

## Reproducing these runs

```bash
# Pre-Park baseline (6 agents — would need to revert constants.py SPECIALISTS)
python3 -m dr_holmes.eval.cli --tier smoke --conditions full_team \
    --n 20 --seed 42 --run-id baseline_pre_park_n20

# Current 7-agent team, no Park authority (v3)
python3 -m dr_holmes.eval.cli --tier smoke --conditions full_team \
    --n 20 --seed 42 --run-id with_park_v3_no_authority_n20
```

Generated reports live in `data/eval_runs/{run_id}/full_team/summary.md`
with reliability charts at `charts/reliability.png` and per-disease
breakdown at `charts/per_disease.png`.

## Per-disease accuracy (top failure cases across all 4 runs)

| Disease | N | Pre-Park | v1 | v2 | v3 |
|---|---|---|---|---|---|
| Possible NSTEMI / STEMI | 3 | 0.33 | 0.00 | 0.00 | 0.33 |
| Chagas | 2 | 0.00 | 0.00 | 0.00 | 0.00 |
| Unstable angina | 2 | 1.00 | 0.50 | 0.50 | 0.50 |
| Pneumonia | 2 | 0.00 | 0.00 | 0.00 | 0.00 |
| Acute otitis media | 1 | 0.00 | 0.00 | 0.00 | 0.00 |
| Viral pharyngitis | 1 | 0.00 | 0.00 | 0.00 | 0.00 |
| Acute laryngitis | 1 | 0.00 | 0.00 | 0.00 | 0.00 |
| Panic attack | 1 | 0.00 | 1.00 | 1.00 | 0.00 |
| Atrial fibrillation | 1 | 1.00 | — | 1.00 | 1.00 |
| HIV (initial) | 1 | — | 1.00 | 1.00 | — |

The infectious-disease cluster (Pneumonia, Viral pharyngitis, Acute otitis
media, Acute laryngitis) is uniformly 0/1 across all four configurations.
Park's anti-zebra voice was specifically designed to catch these and she
didn't. That's the real signal: **the bottleneck isn't Park's authority,
it's the team's collective failure on common infectious dx.** Worth a
targeted Phase 7.5 ablation.
