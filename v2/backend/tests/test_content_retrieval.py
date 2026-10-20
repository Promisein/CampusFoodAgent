import copy

import pytest


def fixture():
    businesses = {item: {"business_id": item, "categories_normalized": ["Restaurants", category],
                         "latitude": lat, "longitude": 0, "price_level": price}
                  for item, category, price, lat in [
                      ("A", "Coffee", 1, 0), ("B", "Coffee", 1, .01),
                      ("C", "Coffee", 4, 1), ("D", "Pizza", 1, 0),
                      ("X", "Coffee", 1, 0)]}
    rows = [{"interaction_id": item, "business_id": item, "user_id": user,
             "rating": 5, "event_time": "2020-01-01"}
            for user, item in [("u", "A"), ("v", "B"), ("w", "C"), ("z", "D")]]
    rows.append({"interaction_id": "future", "business_id": "X", "user_id": "u",
                 "rating": 5, "event_time": "2020-02-01"})
    return rows, businesses


def test_content_finds_category_match_without_cooccurrence_and_prices_break_ties():
    from app.retrieval.content import build_content_index

    rows, businesses = fixture()
    index = build_content_index(rows, businesses, "2020-02-01")
    assert index.recommend("u", "itemcf") == []
    result = index.recommend("u", "content")
    assert [row["business_id"] for row in result] == ["B", "C"]
    assert result[0]["score"] == pytest.approx(1)
    assert result[1]["score"] == pytest.approx(.25)
    assert result[0]["reason_business_ids"] == ["A"]
    assert result[0]["matched_categories"] == ["coffee"]
    assert "restaurants" not in index.idf


def test_snapshot_catalog_is_explicit_and_future_reviews_do_not_change_features():
    from app.retrieval.content import build_content_index

    rows, businesses = fixture()
    strict = build_content_index(rows, businesses, "2020-02-01")
    snapshot = build_content_index(rows, businesses, "2020-02-01", catalog_policy="snapshot_catalog")
    assert "X" not in strict.visible_business_ids
    assert "X" in snapshot.visible_business_ids
    assert "X" in [row["business_id"] for row in snapshot.recommend("u", "content")]
    changed = copy.deepcopy(rows)
    changed[-1]["rating"] = 1
    changed[-1]["user_id"] = "new"
    repeated = build_content_index(changed, businesses, "2020-02-01", catalog_policy="snapshot_catalog")
    assert snapshot.recommend("u", "content") == repeated.recommend("u", "content")
    assert snapshot.profile("u")["history_count"] == 1


def test_content_has_no_invented_cold_preferences_and_merge_falls_back():
    from app.retrieval.content import build_content_index

    rows, businesses = fixture()
    index = build_content_index(rows, businesses, "2020-02-01")
    assert index.recommend("cold", "content") == []
    assert index.recommend("cold", "combined_content") == index.recommend("cold", "popularity")
    result = index.recommend("u", "combined_content", limit=3)
    assert len(result) == len({row["business_id"] for row in result})
    assert "A" not in {row["business_id"] for row in result}


def test_content_obeys_geo_pool_and_is_deterministic():
    from app.retrieval.content import build_content_index

    rows, businesses = fixture()
    index = build_content_index(rows, businesses, "2020-02-01")
    assert [row["business_id"] for row in index.recommend("u", "content", radius_km=10)] == ["B"]
    other = build_content_index(list(reversed(rows)), businesses, "2020-02-01")
    assert index.recommend("u", "combined_content") == other.recommend("u", "combined_content")


def test_existing_sources_remain_identical_to_previous_baseline():
    from app.retrieval.baselines import build_index
    from app.retrieval.content import build_content_index

    rows, businesses = fixture()
    baseline = build_index(rows, businesses, "2020-02-01")
    content = build_content_index(rows, businesses, "2020-02-01")
    for source in ("popularity", "itemcf", "combined"):
        assert content.recommend("u", source) == baseline.recommend("u", source)


def test_unknown_catalog_policy_fails():
    from app.retrieval.content import build_content_index

    rows, businesses = fixture()
    with pytest.raises(ValueError):
        build_content_index(rows, businesses, "2020-02-01", catalog_policy="invent")


def test_content_model_is_byte_reproducible_across_python_hash_seeds():
    import os
    import subprocess
    import sys

    code = '''
import json
from app.retrieval.content import build_content_index
businesses = {str(i): {"business_id": str(i), "categories_normalized": ["category"+str(j) for j in range(37-i)], "latitude":0,"longitude":0,"price_level":1} for i in range(20)}
rows = [{"interaction_id":str(i),"user_id":str(i),"business_id":str(i),"rating":5,"event_time":"2020-01-01"} for i in range(20)]
print(json.dumps(build_content_index(rows,businesses,"2020-02-01").content_model(),sort_keys=True))
'''
    outputs = [subprocess.check_output([sys.executable, "-B", "-c", code],
                                      env={**os.environ, "PYTHONHASHSEED": str(seed)})
               for seed in (1, 2)]
    assert outputs[0] == outputs[1]
