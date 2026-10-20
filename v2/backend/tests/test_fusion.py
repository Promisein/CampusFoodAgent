import math

import pytest


def rec(item, score=1, seed=None):
    return {"business_id": item, "score": score,
            "reason_business_ids": [seed] if seed else []}


def test_rrf_is_rank_based_and_preserves_each_channel_provenance():
    from app.ranking.fusion import fuse_rrf

    result = fuse_rrf({"popularity": [rec("A", 99), rec("B", 1)],
                       "itemcf": [rec("B", .2, "S"), rec("C", .1)]}, k=10)
    assert [r["business_id"] for r in result] == ["B", "A", "C"]
    assert result[0]["score"] == pytest.approx(1/12 + 1/11)
    assert result[0]["channel_scores"]["itemcf"] == {"rank": 1, "raw_score": .2}
    assert result[0]["reason_business_ids"] == ["S"]


def test_weight_budget_whitelist_and_duplicate_handling():
    from app.ranking.fusion import fuse_rrf

    result = fuse_rrf({"popularity": [rec("A"), rec("A"), rec("B")],
                       "content": [rec("C"), rec("B")]}, weights={"popularity": 2, "content": 0},
                      budgets={"popularity": 3}, allowed={"A", "B"}, k=1)
    assert [r["business_id"] for r in result] == ["A", "B"]
    assert result[0]["score"] == 1
    assert result[1]["score"] == pytest.approx(2/3)


def test_rrf_ties_and_input_channel_order_are_deterministic():
    from app.ranking.fusion import fuse_rrf

    channels = {"content": [rec("B")], "itemcf": [rec("A")]}
    assert fuse_rrf(channels) == fuse_rrf(dict(reversed(list(channels.items()))))
    assert fuse_rrf(channels)[0]["business_id"] == "A"
    assert fuse_rrf({}) == []


@pytest.mark.parametrize("kwargs", [{"k": 0}, {"weights": {"itemcf": -1}},
                                    {"weights": {"itemcf": math.nan}},
                                    {"budgets": {"itemcf": 101}}, {"limit": 0}])
def test_invalid_fusion_configuration_fails(kwargs):
    from app.ranking.fusion import fuse_rrf

    with pytest.raises(ValueError):
        fuse_rrf({"itemcf": [rec("A")]}, **kwargs)
