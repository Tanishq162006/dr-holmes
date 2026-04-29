"""Aggregate per-specialist Ddx into a team-level differential.

Rule: union of every specialist's top-3 dx. For each unique dx, team
probability = mean of specialists who proposed it (weighted by their
confidence). Sort desc.
"""
from __future__ import annotations
import re
from collections import defaultdict

from dr_holmes.models.core import Differential as TeamDifferential
from dr_holmes.schemas.responses import Differential as SpecDifferential


def _norm(name: str) -> str:
    """Normalize disease name for matching: lowercase, drop parentheticals,
    drop punctuation, collapse whitespace."""
    s = (name or "").lower()
    # drop parenthetical / bracket clarifiers
    s = re.sub(r"\([^)]*\)", " ", s)
    s = re.sub(r"\[[^\]]*\]", " ", s)
    # drop trailing qualifier after a comma or colon
    s = re.split(r"[,:;]", s)[0]
    s = s.replace("'s", "").replace("'", "")
    s = re.sub(r"[^a-z0-9 ]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def _merge_substring_keys(buckets: dict) -> dict:
    """Second pass: if bucket key A is a strict substring of bucket key B
    (both ≥ 4 chars to avoid matching 'a'/'an'), merge B into A. Keeps the
    shorter canonical form."""
    keys = sorted(buckets.keys(), key=len)
    merged: dict = {}
    canonical_of: dict[str, str] = {}
    for k in keys:
        if len(k) < 4:
            merged[k] = buckets[k]; canonical_of[k] = k
            continue
        match = None
        for canon in merged:
            if len(canon) < 4: continue
            # token-set match: every token of canon must be in k
            canon_toks = set(canon.split())
            k_toks = set(k.split())
            if canon_toks.issubset(k_toks) or k_toks.issubset(canon_toks):
                match = canon; break
        if match:
            target = merged[match]
            src = buckets[k]
            target["probs"].extend(src["probs"])
            target["weights"].extend(src["weights"])
            target["proposers"].update(src["proposers"])
            target["supports"].update(src["supports"])
            target["againsts"].update(src["againsts"])
            # keep shorter canonical name
            if len(src["name"]) < len(target["name"]):
                target["name"] = src["name"]
        else:
            merged[k] = buckets[k]
            canonical_of[k] = k
    return merged


def aggregate_team_differential(
    agent_responses: dict[str, list],
) -> list[TeamDifferential]:
    """Returns team-level Ddx as the dr_holmes.models.core.Differential type
    (compatible with Phase 2 BayesEngine outputs)."""
    bucket: dict[str, dict] = defaultdict(lambda: {
        "name": "", "probs": [], "weights": [],
        "supports": set(), "againsts": set(), "proposers": set(),
    })

    for agent, hist in agent_responses.items():
        if not hist:
            continue
        # Use the most recent NON-EMPTY response — preserves position when
        # the agent didn't speak this round (mock fixtures return empty).
        last = None
        for r in reversed(hist):
            diffs_check = getattr(r, "differentials", None)
            if diffs_check is None and isinstance(r, dict):
                diffs_check = r.get("differentials", [])
            if diffs_check:
                last = r
                break
        if last is None:
            continue
        diffs = getattr(last, "differentials", None)
        if diffs is None and isinstance(last, dict):
            diffs = last.get("differentials", [])
        if not diffs:
            continue
        if isinstance(last, dict):
            agent_conf = float(last.get("confidence", 0.5))
        else:
            agent_conf = float(getattr(last, "confidence", 0.5))

        for d in diffs[:3]:
            name = (d.diagnosis if hasattr(d, "diagnosis") else d.get("diagnosis", "")) or ""
            if not name:
                continue
            key = _norm(name)
            b = bucket[key]
            if not b["name"]:
                b["name"] = name
            prob = float(d.probability if hasattr(d, "probability") else d.get("probability", 0.0))
            b["probs"].append(prob)
            b["weights"].append(max(agent_conf, 0.1))
            b["proposers"].add(agent)
            sup = (d.supporting_evidence if hasattr(d, "supporting_evidence")
                   else d.get("supporting_evidence", [])) or []
            agn = (d.contradicting_evidence if hasattr(d, "contradicting_evidence")
                   else d.get("contradicting_evidence", [])) or []
            for s in sup:    b["supports"].add(s)
            for a in agn:    b["againsts"].add(a)

    # Second-pass: merge substring/superset keys ("Anterior STEMI" ⊆ "Anterior STEMI requiring revasc")
    bucket = _merge_substring_keys(dict(bucket))

    out: list[TeamDifferential] = []
    for key, b in bucket.items():
        if not b["probs"]:
            continue

        n_agree = len(b["proposers"])
        weighted_mean = sum(p * w for p, w in zip(b["probs"], b["weights"])) / (sum(b["weights"]) or 1.0)

        # Strong consensus: ≥3 specialists at >0.4 → noisy-OR model.
        # Treats each specialist's belief as an independent positive predictor;
        # captures the intuition that 4 doctors saying "60% likely SLE"
        # collectively means more than any one alone.
        eligible = [p for p in b["probs"] if p > 0.4]
        if n_agree >= 3 and len(eligible) >= 3:
            noisy_or = 1.0
            for p in eligible:
                noisy_or *= (1.0 - p)
            noisy_or = 1.0 - noisy_or
            # Pick the higher of the two estimates, capped
            team_prob = min(max(weighted_mean, noisy_or), 0.97)
        elif n_agree == 2:
            team_prob = min(weighted_mean * 1.10, 0.95)
        else:
            team_prob = weighted_mean
        out.append(TeamDifferential(
            disease=b["name"],
            probability=team_prob,
            supporting_evidence=sorted(b["supports"]),
            against_evidence=sorted(b["againsts"]),
            proposed_by=", ".join(sorted(b["proposers"])),
        ))

    # Renormalize so total ≤ 1.0 (probability mass conservation)
    total = sum(d.probability for d in out)
    if total > 1.0:
        for d in out:
            d.probability = d.probability / total

    return sorted(out, key=lambda d: d.probability, reverse=True)


def _turn(resp) -> int:
    if isinstance(resp, dict):
        return int(resp.get("turn_number", 0))
    return int(getattr(resp, "turn_number", 0))


def collect_active_challenges(agent_responses: dict[str, list]) -> list[dict]:
    """A challenge is *active* until its target agent speaks in a later round
    than the round the challenge was raised. Once the target has had a chance
    to respond, the challenge is considered resolved."""
    out = []
    for agent, hist in agent_responses.items():
        if not hist:
            continue
        for resp in hist:
            chs = getattr(resp, "challenges", None)
            if chs is None and isinstance(resp, dict):
                chs = resp.get("challenges", [])
            if not chs:
                continue
            t_raise = _turn(resp)
            for c in chs:
                target = (c.target_agent if hasattr(c, "target_agent")
                          else c.get("target_agent", "") if isinstance(c, dict) else "")
                target_hist = agent_responses.get(target, [])
                # If target spoke in a strictly later round → challenge resolved
                resolved = any(_turn(t) > t_raise for t in target_hist)
                if resolved:
                    continue
                out.append(c.model_dump() if hasattr(c, "model_dump") else dict(c))
    return out
