"""Deterministic weighted reciprocal-rank fusion with source provenance."""

import math


def fuse_rrf(channels, *, weights=None, k=60, budgets=None, limit=100, allowed=None):
    weights = {name: 1.0 for name in channels} if weights is None else weights
    budgets = {} if budgets is None else budgets
    if not math.isfinite(k) or k <= 0 or not isinstance(limit, int) or limit < 1:
        raise ValueError("k and limit must be positive")
    if any(not math.isfinite(weight) or weight < 0 for weight in weights.values()):
        raise ValueError("Fusion weights must be finite/nonnegative")
    if any(not isinstance(budget, int) or not 0 <= budget <= 100 for budget in budgets.values()):
        raise ValueError("Channel budgets must be integers in 0..100")
    merged = {}
    for source in sorted(channels):
        weight = weights.get(source, 0)
        if weight == 0:
            continue
        unique, seen = [], set()
        for rec in channels[source]:
            item = rec["business_id"]
            if item not in seen:
                unique.append(rec)
                seen.add(item)
        for rank, rec in enumerate(unique[:budgets.get(source, 100)], start=1):
            item = rec["business_id"]
            if allowed is not None and item not in allowed:
                continue
            raw_score = float(rec["score"])
            if not math.isfinite(raw_score):
                raise ValueError("Nonfinite channel score")
            row = merged.setdefault(item, {"business_id": item, "score": 0.0,
                                          "channel_scores": {}, "reason_business_ids": set(),
                                          "matched_categories": set()})
            row["score"] += weight / (k + rank)
            row["channel_scores"][source] = {"rank": rank, "raw_score": raw_score}
            row["reason_business_ids"].update(rec.get("reason_business_ids", []))
            row["matched_categories"].update(rec.get("matched_categories", []))
    result = sorted(merged.values(), key=lambda row: (-row["score"], row["business_id"]))[:limit]
    for row in result:
        row["reason_business_ids"] = sorted(row["reason_business_ids"])
        row["matched_categories"] = sorted(row["matched_categories"])
    return result
