"""Phase 3 routing & convergence constants — locked values."""

# ── Convergence ────────────────────────────────────────────────────────────
CONVERGENCE_PROB = 0.80   # team-level top-Dx probability threshold
AGREEMENT_COUNT  = 3      # specialists who must agree (out of 5)
AGREEMENT_PROB   = 0.50   # each agreeing specialist must have prob > this
STABILITY_DELTA  = 0.05   # last-round top-dx probability movement < this

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
SPECIALISTS = ["Hauser", "Forman", "Carmen", "Chen", "Wills"]
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
}
