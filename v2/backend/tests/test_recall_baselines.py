import math

import pytest


def event(user, item, rating=5, time="2020-01-01", event_id=None):
    return {
        "interaction_id": event_id or f"{user}-{item}-{time}",
        "user_id": user, "business_id": item, "rating": rating,
        "event_time": time,
    }


def businesses():
    return {
        item: {"business_id": item, "categories_normalized": [category],
               "latitude": lat, "longitude": 0, "price_level": price,
               "stars": 1, "review_count": 999999, "is_open": False}
        for item, category, lat, price in [
            ("A", "Coffee", 0, 1), ("B", "Coffee", 0.01, 2),
            ("C", "Pizza", 1, 3), ("D", "Pizza", 0, None),
            ("FUTURE", "Coffee", 0, 1),
        ]
    }


def test_itemcf_cosine_and_explanation_use_only_past_positive_pairs():
    from app.retrieval.baselines import build_index

    rows = [event("u1", "A"), event("u1", "B"), event("u2", "A"),
            event("u2", "C"), event("target", "A", 4),
            event("bad", "A", 1), event("bad", "D", 1),
            event("target", "FUTURE", time="2020-02-01")]
    index = build_index(rows, businesses(), "2020-02-01", shrinkage=0)
    recs = index.recommend("target", "itemcf")
    assert [r["business_id"] for r in recs] == ["B", "C"]
    assert recs[0]["score"] == pytest.approx(1 / math.sqrt(3))
    assert recs[0]["reason_business_ids"] == ["A"]
    assert "FUTURE" not in index.visible_business_ids
    assert index.profile("target")["history_count"] == 1


def test_latest_low_rating_removes_positive_pair_but_keeps_seen_exclusion():
    from app.retrieval.baselines import build_index

    rows = [event("u", "A"), event("u", "A", 1, "2020-01-02"),
            event("u", "B"), event("other", "A"), event("other", "B")]
    index = build_index(rows, businesses(), "2020-02-01")
    assert index.profile("u")["positive_business_ids"] == ["B"]
    assert index.recommend("u", "itemcf") == []
    assert index.popularity["A"]["positive_users"] == 1


def test_shrinkage_penalizes_single_support_and_ties_are_stable():
    from app.retrieval.baselines import build_index

    rows = [event("u1", "A"), event("u1", "B"),
            event("u2", "A"), event("u2", "B"),
            event("u3", "A"), event("u3", "C"), event("target", "A")]
    index = build_index(rows, businesses(), "2020-02-01", shrinkage=5)
    assert index.neighbors["A"][0]["business_id"] == "B"
    assert index.neighbors["A"][0]["support"] == 2
    assert index.neighbors["A"][0]["similarity"] == pytest.approx(2 / math.sqrt(8) * 2 / 7)
    reversed_index = build_index(list(reversed(rows)), businesses(), "2020-02-01")
    assert index.neighbors == reversed_index.neighbors


def test_geo_filters_distance_and_unknown_prices_without_using_snapshot_open_flag():
    from app.retrieval.baselines import build_index

    rows = [event("target", "A"), event("other", "B"),
            event("other", "C"), event("other", "D")]
    index = build_index(rows, businesses(), "2020-02-01")
    recs = index.recommend("target", "popularity", radius_km=10)
    assert [r["business_id"] for r in recs] == ["B"]
    assert recs[0]["distance_km"] == pytest.approx(1.11195, rel=1e-4)
    assert index.recommend("unknown", "popularity", radius_km=10) == []
    assert index.recommend("target", "popularity", radius_km=10, max_price_level=1) == []


def test_merge_deduplicates_and_cold_user_falls_back_to_popularity():
    from app.retrieval.baselines import build_index

    rows = [event("u", "A"), event("u", "B"), event("target", "A"),
            event("v", "C"), event("w", "C"), event("z", "D")]
    index = build_index(rows, businesses(), "2020-02-01")
    result = index.recommend("target", "combined", limit=3)
    assert [r["business_id"] for r in result] == ["B", "C", "D"]
    assert len({r["business_id"] for r in result}) == 3
    assert index.recommend("new", "itemcf") == []
    assert [r["business_id"] for r in index.recommend("new", "combined")] == [
        r["business_id"] for r in index.recommend("new", "popularity")]


def test_popularity_uses_historical_ratings_not_business_snapshot_statistics():
    from app.retrieval.baselines import build_index

    index = build_index([event("u", "A", 5), event("v", "B", 1)], businesses(), "2020-02-01")
    assert index.popularity["A"]["mean_rating"] == 5
    assert index.popularity["A"]["score"] > index.popularity["B"]["score"]
    assert index.profile("new")["cohort"] == "cold"


@pytest.mark.parametrize("change", ["duplicate", "unknown", "rating", "time"])
def test_invalid_interactions_fail_instead_of_silently_biasing_metrics(change):
    from app.retrieval.baselines import build_index

    rows = [event("u", "A")]
    if change == "duplicate":
        rows *= 2
    else:
        rows[0][{"unknown": "business_id", "rating": "rating", "time": "event_time"}[change]] = {
            "unknown": "missing", "rating": 6, "time": "bad"}[change]
    with pytest.raises(ValueError):
        build_index(rows, businesses(), "2020-02-01")
