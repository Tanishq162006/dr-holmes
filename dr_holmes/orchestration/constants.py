"""Phase 3 routing & convergence constants — locked values."""

# ── Convergence ────────────────────────────────────────────────────────────
CONVERGENCE_PROB = 0.80   # team-level top-Dx probability threshold
AGREEMENT_COUNT  = 3      # specialists who must agree (out of 6 with Park)
AGREEMENT_PROB   = 0.50   # each agreeing specialist must have prob > this
STABILITY_DELTA  = 0.05   # last-round top-dx probability movement < this

# ── Park's authority on confidence ─────────────────────────────────────────
# When Park's top-dx confidence ≥ this, her vote counts double in the
# cross-specialist agreement check AND her probability gets a multiplier
# in noisy-OR aggregation. Anchors the team toward common diagnoses when
# she's confident, while preserving Hauser's right to dissent.
# Tightened after n=20 eval: 0.70 + 1.30× drove ECE from 0.17 → 0.37 because
# Park's wrong-but-confident answers got amplified. Raise the bar (only fires
# when she's clearly anchored) and lower the multiplier (still meaningful, no
# longer dominant). Vote-doubling in convergence kept but gated by same higher
# threshold.
PARK_AUTHORITY_THRESHOLD = 0.85
PARK_AUTHORITY_WEIGHT    = 1.15   # multiplier on her prob in noisy-OR
PARK_LOW_THRESHOLD_BUMP  = 0.10   # when Park is very confident, lower
                                    # CONVERGENCE_PROB by this for HER dx only

# ── Round limits ───────────────────────────────────────────────────────────
MAX_ROUNDS = 6
MIN_ROUNDS_BEFORE_CONVERGE = 2

# ── Anti-stagnation ────────────────────────────────────────────────────────
# 2 consecutive rounds with delta < STAGNATION_DELTA AND no new evidence
# → force a discriminating test instead of continued debate
STAGNATION_DELTA  = 0.02
STAGNATION_ROUNDS = 2

# ── Privileges ─────────────────────────────────────────────────────────────
HAUSER_INTERRUPTS_PER_CASE = 1

# ── Specialists ────────────────────────────────────────────────────────────
SPECIALISTS = ["Hauser", "Forman", "Carmen", "Chen", "Wills", "Park"]
MODERATOR = "Caddick"

# ── Specialty routing lookup ───────────────────────────────────────────────
# Maps a disease category to the specialist most likely to add value
SPECIALTY_LOOKUP: dict[str, str] = {
    "autoimmune":      "Carmen",
    "rheumatologic":   "Carmen",
    "immune":          "Carmen",
    "malignancy":      "Wills",
    "cancer":          "Wills",
    "oncologic":       "Wills",
    "surgical":        "Chen",
    "procedural":      "Chen",
    "icu":             "Chen",
    "trauma":          "Chen",
    "neurologic":      "Forman",
    "internal":        "Forman",
    "rare":            "Hauser",
    "zebra":           "Hauser",
    # Park — common-presentation primary care
    "common":          "Park",
    "outpatient":      "Park",
    "viral":           "Park",
    "respiratory":     "Park",
    "ent":             "Park",
}
