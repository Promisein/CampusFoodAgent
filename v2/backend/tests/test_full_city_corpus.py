import hashlib
import json

import pytest


def sources(tmp_path):
    business = tmp_path / "businesses.jsonl"
    business.write_text(json.dumps({"business_id": "A", "city": "Tampa", "state": "FL"}) + "\n", encoding="utf-8")
    reviews = tmp_path / "reviews.json"
    rows = [{"review_id": str(i), "user_id": f"u{i}", "business_id": "A",
             "stars": 5, "date": "2020-01-01", "text": "do not duplicate text"}
            for i in range(45)]
    rows.append({"review_id": "other", "business_id": "B"})
    reviews.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
    return reviews, business, rows


def test_full_city_keeps_all_reviews_and_compact_fields(tmp_path):
    from app.data_pipeline.full_city_corpus import build_full_city_corpus

    reviews, business, _ = sources(tmp_path)
    out = tmp_path / "full"
    manifest = build_full_city_corpus(reviews, business, out)
    rows = [json.loads(line) for line in (out / "interactions.jsonl").read_text().splitlines()]
    assert len(rows) == 45
    assert manifest["kept"]["interactions"] == 45
    assert manifest["discarded"]["outside_business_universe"] == 1
    assert manifest["inputs"]["reviews"]["sha256"] == hashlib.sha256(reviews.read_bytes()).hexdigest()
    assert rows[0]["interaction_id"] == "0"
    assert rows[0]["event_type"] == "review"
    assert all("text" not in row and "review_text" not in row for row in rows)
    assert (out / "businesses.jsonl").read_bytes() == business.read_bytes()
    first = {path.name: path.read_bytes() for path in out.iterdir()}
    build_full_city_corpus(reviews, business, out)
    assert first == {path.name: path.read_bytes() for path in out.iterdir()}


@pytest.mark.parametrize("change", ["duplicate", "rating", "date", "user"])
def test_bad_selected_review_fails_without_publishing_partial_dataset(tmp_path, change):
    from app.data_pipeline.full_city_corpus import build_full_city_corpus

    reviews, business, rows = sources(tmp_path)
    if change == "duplicate":
        rows.append(rows[0])
    else:
        rows[0][{"rating": "stars", "date": "date", "user": "user_id"}[change]] = {
            "rating": 9, "date": "invalid", "user": ""}[change]
    reviews.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
    out = tmp_path / "full"
    with pytest.raises(ValueError):
        build_full_city_corpus(reviews, business, out)
    assert not out.exists()


def test_corpus_refuses_input_and_existing_unrelated_directories(tmp_path):
    from app.data_pipeline.full_city_corpus import build_full_city_corpus

    reviews, business, _ = sources(tmp_path)
    for out in (tmp_path, reviews):
        with pytest.raises(ValueError):
            build_full_city_corpus(reviews, business, out)
    out = tmp_path / "old"
    out.mkdir()
    (out / "keep").write_text("keep")
    with pytest.raises(ValueError):
        build_full_city_corpus(reviews, business, out)
    assert (out / "keep").read_text() == "keep"


def test_corpus_manifest_tracks_validator_and_detects_tampered_artifacts(tmp_path):
    from pathlib import Path
    from app.data_pipeline.full_city_corpus import build_full_city_corpus
    from app.retrieval import baselines
    from app.artifact_io import verify_artifacts

    reviews, business, _ = sources(tmp_path)
    out = tmp_path / "full"
    manifest = build_full_city_corpus(reviews, business, out)
    assert manifest["code_sha256"]["baselines.py"] == hashlib.sha256(Path(baselines.__file__).read_bytes()).hexdigest()
    verify_artifacts(out, "data_manifest.json")
    with (out / "interactions.jsonl").open("a") as changed:
        changed.write("{}\n")
    with pytest.raises(ValueError):
        verify_artifacts(out, "data_manifest.json")
