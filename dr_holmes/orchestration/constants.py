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
# DISABLED after two n=20 evals (0.70/1.30 then 0.85/1.15) both hurt headline
# accuracy and ECE relative to pre-Park baseline. Park's confident anchor on
# common dx pulled #1 toward her pick even when wrong, and the team
# prematurely converged on it (+15pp new failure mode). Park stays as a
# normal-weighted voice; her prompt persona still pushes back on Hauser's
# zebras, but no aggregation/convergence multiplier. To re-enable, raise
# PARK_AUTHORITY_WEIGHT > 1.0 and lower PARK_AUTHORITY_THRESHOLD < 1.01.
PARK_AUTHORITY_THRESHOLD = 1.01   # > 1.0 means never fires
PARK_AUTHORITY_WEIGHT    = 1.00   # no multiplier
PARK_LOW_THRESHOLD_BUMP  = 0.00   # no convergence threshold bump

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
