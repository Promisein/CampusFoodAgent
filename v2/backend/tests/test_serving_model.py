import json
from concurrent.futures import ThreadPoolExecutor

import pytest


def make_snapshot(tmp_path):
    from app.serving.model import build_serving_snapshot

    source = tmp_path / "source"
    source.mkdir()
    businesses = {item: {"business_id": item, "name": item, "categories_raw": category,
                         "categories_normalized": [category], "latitude": lat, "longitude": 0,
                         "city": "Tampa", "state": "FL", "stars": 4, "review_count": 10,
                         "price_level": price, "hours": {}, "attributes": {}, "is_open": opened,
                         "data_version": "fixture"}
                  for item, category, lat, price, opened in [
                      ("A", "Coffee", 0, 1, True), ("B", "Coffee", .01, 1, True),
                      ("C", "Pizza", .02, 2, True), ("D", "Coffee", .01, 1, False),
                      ("E", "Coffee", 1, 1, True), ("F", "Coffee", .01, None, True)]}
    entries = [("u", "A"), ("v", "C"), ("other", "A"), ("other", "B"),
               ("x", "C"), ("x", "B"), ("d", "D"), ("e", "E"), ("f", "F")]
    rows = [{"interaction_id": str(i), "user_id": user, "business_id": item,
             "rating": 5, "event_time": "2020-01-01"} for i, (user, item) in enumerate(entries)]
    for name, records in (("businesses.jsonl", businesses.values()), ("interactions.jsonl", rows)):
        (source / name).write_text("".join(json.dumps(row)+"\n" for row in records), encoding="utf-8")
    (source / "representative_reviews.jsonl").write_text("", encoding="utf-8")
    config = {"name": "fixture", "mode": "rrf", "k": 60,
              "weights": {"popularity": 1, "itemcf": 1, "content": .25},
              "budgets": {"popularity": 100, "itemcf": 100, "content": 100}}
    selection = {scenario: config for scenario in ("city_preference", "simulated_geo")}
    out = tmp_path / "serving"
    build_serving_snapshot(source, selection, out)
    return source, out, businesses, rows


def request(user):
    from app.models import RecommendationRequest
    return RecommendationRequest(query="coffee", user_id=user, latitude=0, longitude=0,
                                 radius_km=10, max_price_level=2, top_k=5)


def test_serving_loads_versioned_profiles_and_matches_offline_scores(tmp_path):
    from app.serving.model import ServingRepository, RequestRecallIndex
    from app.retrieval.content import build_content_index

    _, out, businesses, rows = make_snapshot(tmp_path)
    repository = ServingRepository(out)
    bundle = repository.load()
    assert repository.load() is bundle
    assert bundle["manifest"]["snapshot_cutoff"] > "2020-01-01"
    index = RequestRecallIndex(bundle, businesses, request("u"))
    offline = build_content_index(rows, businesses, bundle["manifest"]["snapshot_cutoff"])
    allowed, _, _ = index.candidate_pool("u")
    assert allowed == {"B", "C"}
    for source in ("itemcf", "content"):
        actual = index.recommend("u", source)
        expected = [r for r in offline.recommend("u", source) if r["business_id"] in allowed]
        assert [(r["business_id"], r["score"]) for r in actual] == [(r["business_id"], r["score"]) for r in expected]


def test_request_scoped_indices_do_not_cross_contaminate_users(tmp_path):
    from app.serving.model import ServingRepository, RequestRecallIndex

    _, out, businesses, _ = make_snapshot(tmp_path)
    bundle = ServingRepository(out).load()

    def run(user):
        index = RequestRecallIndex(bundle, businesses, request(user))
        return user, [r["business_id"] for r in index.recommend(user, "popularity")]

    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(run, ["u", "v"] * 10))
    assert all("A" not in ids for user, ids in results if user == "u")
    assert all("C" not in ids for user, ids in results if user == "v")
    assert results[0][1] != results[1][1]


def test_missing_content_channel_is_disabled_but_mandatory_corruption_fails(tmp_path):
    from app.serving.model import ServingRepository

    _, out, _, _ = make_snapshot(tmp_path)
    (out / "content.json").unlink()
    bundle = ServingRepository(out).load()
    assert "content" in bundle["disabled_channels"]
    with (out / "profiles.jsonl").open("a") as changed:
        changed.write("{}\n")
    with pytest.raises(ValueError):
        ServingRepository(out).load()


def test_serving_export_is_deterministic_and_does_not_overwrite_inputs(tmp_path):
    from app.serving.model import build_serving_snapshot

    source, out, _, _ = make_snapshot(tmp_path)
    before = {path.name: path.read_bytes() for path in out.iterdir()}
    selection = json.loads((out / "manifest.json").read_text())["selection"]
    build_serving_snapshot(source, selection, out)
    assert before == {path.name: path.read_bytes() for path in out.iterdir()}
    with pytest.raises(ValueError):
        build_serving_snapshot(source, selection, source)

@pytest.mark.parametrize('filename,payload,channel', [
    ('popularity.json', None, 'popularity'),
    ('neighbors.json', [], 'itemcf'),
    ('content.json', {'cutoff': '2020-01-02 00:00:00', 'item_vectors': []}, 'content'),
])
def test_channel_failure_preserves_profiles_and_healthy_channels(tmp_path, filename, payload, channel):
    from app.serving.model import ServingRepository, RequestRecallIndex
    from app.artifact_io import file_sha256
    _, out, businesses, _ = make_snapshot(tmp_path)
    path = out / filename
    if payload is None:
        path.unlink()
    else:
        path.write_text(json.dumps(payload), encoding='utf-8')
        manifest = json.loads((out / 'manifest.json').read_text())
        manifest['outputs'][filename] = {'bytes': path.stat().st_size, 'sha256': file_sha256(path)}
        (out / 'manifest.json').write_text(json.dumps(manifest), encoding='utf-8')
    bundle = ServingRepository(out).load()
    assert bundle['disabled_channels'] == (channel,)
    assert bundle['profiles']['u']['seen_business_ids'] == ['A']
    index = RequestRecallIndex(bundle, businesses, request('u'))
    assert index.candidate_pool('u')[0] == {'B', 'C'}
    healthy = 'content' if channel != 'content' else 'itemcf'
    assert index.recommend('u', healthy)


def test_selection_digest_is_verified_on_load(tmp_path):
    from app.serving.model import ServingRepository
    _, out, _, _ = make_snapshot(tmp_path)
    path = out / 'manifest.json'
    manifest = json.loads(path.read_text())
    manifest['selection']['simulated_geo']['weights']['itemcf'] = 10000
    path.write_text(json.dumps(manifest), encoding='utf-8')
    with pytest.raises(ValueError, match='selection'):
        ServingRepository(out).load()

@pytest.mark.parametrize('value', [[], {'simulated_geo': [], 'city_preference': []}])
def test_invalid_selection_shapes_raise_recoverable_errors(tmp_path, value):
    from app.serving.model import ServingRepository
    _, out, _, _ = make_snapshot(tmp_path)
    path = out / 'manifest.json'
    manifest = json.loads(path.read_text())
    manifest['selection'] = value
    path.write_text(json.dumps(manifest), encoding='utf-8')
    with pytest.raises(ValueError):
        ServingRepository(out).load()
