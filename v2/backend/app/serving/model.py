"""Load frozen artifacts; online requests never train or load raw reviews."""

import argparse
import hashlib
import json
import math
import tempfile
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from threading import Lock

from app import artifact_io
from app.evaluation import baseline_replay
from app.ranking import fusion
from app.retrieval import baselines, content


MODEL_VERSION = "serving_v1"
CHANNELS = ("popularity", "itemcf", "content")


def validate_selection(selection):
    if not isinstance(selection, dict):
        raise ValueError("Invalid selection object")
    for scenario in ("city_preference", "simulated_geo"):
        config = selection[scenario]
        if not isinstance(config, dict) or not isinstance(config.get("weights"), dict) or not isinstance(config.get("budgets"), dict):
            raise ValueError("Invalid selection configuration")
        if config.get("mode") != "rrf" or set(config["weights"]) != set(CHANNELS):
            raise ValueError("Serving requires a known RRF channel configuration")
        fusion.fuse_rrf({}, weights=config["weights"], k=config["k"], budgets=config["budgets"])
        if not any(config["weights"][channel] > 0 and config["budgets"].get(channel, 100) > 0 for channel in CHANNELS):
            raise ValueError("At least one serving channel must be enabled")


def build_serving_snapshot(data_dir, selection, output_dir, *, provenance=None):
    validate_selection(selection)
    data_dir, output_dir = Path(data_dir).resolve(), Path(output_dir).resolve()
    if data_dir == output_dir or data_dir in output_dir.parents or output_dir in data_dir.parents:
        raise ValueError("Serving output must be separate from data")
    if output_dir.exists() and any(output_dir.iterdir()):
        path = output_dir / "manifest.json"
        if not path.exists() or json.loads(path.read_text(encoding="utf-8")).get("model_version") != MODEL_VERSION:
            raise ValueError("Unrelated serving directory")
    if (data_dir / "data_manifest.json").exists():
        artifact_io.verify_artifacts(data_dir, "data_manifest.json")
    paths = [data_dir / name for name in ("businesses.jsonl", "interactions.jsonl")]
    hashes = {path.name: artifact_io.file_sha256(path) for path in paths}
    business_rows = baseline_replay._read_jsonl(paths[0])
    businesses = {row["business_id"]: row for row in business_rows}
    if len(businesses) != len(business_rows):
        raise ValueError("Duplicate businesses")
    rows = baselines.validate_interactions(baseline_replay._read_jsonl(paths[1]), businesses)
    if not rows:
        raise ValueError("No serving history")
    cutoff = (datetime.fromisoformat(rows[-1]["event_time"]).replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)).isoformat(sep=" ")
    index = content.build_content_index(rows, businesses, cutoff)
    manifest = {"model_version": MODEL_VERSION, "profile_version": "full_history_snapshot_v1",
                "snapshot_cutoff": cutoff, "data_max_time": rows[-1]["event_time"],
                "selection": selection, "selection_sha256": hashlib.sha256(json.dumps(selection, sort_keys=True).encode()).hexdigest(),
                "selection_provenance": provenance or {}, "catalog_ids": sorted(index.visible_business_ids),
                "profile_count": len(index.profiles), "history_events": len(index.history),
                "inputs": {path.name: {"sha256": hashes[path.name], "bytes": path.stat().st_size} for path in paths},
                "code_sha256": {Path(module).name: artifact_io.file_sha256(module) for module in (
                    __file__, content.__file__, baselines.__file__, baseline_replay.__file__, fusion.__file__, artifact_io.__file__)},
                "usage": "offline historical demo snapshot, not live user activity or a test-evaluation model"}
    output_dir.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".serving-", dir=output_dir.parent) as temporary:
        stage = Path(temporary)
        with (stage / "profiles.jsonl").open("w", encoding="utf-8") as out:
            for user, profile in sorted(index.profiles.items()):
                out.write(json.dumps(profile, sort_keys=True) + "\n")
        for name, value in (("neighbors.json", index.neighbors), ("popularity.json", index.popularity),
                            ("content.json", index.content_model())):
            (stage / name).write_text(json.dumps(value, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")
        if hashes != {path.name: artifact_io.file_sha256(path) for path in paths}:
            raise RuntimeError("Serving inputs changed")
        artifact_io.publish_directory(stage, output_dir, manifest, "manifest.json")
    return manifest


class ServingRepository:
    def __init__(self, model_dir):
        self.model_dir = Path(model_dir)
        self._bundle = None
        self._lock = Lock()

    def load(self):
        with self._lock:
            if self._bundle is not None:
                return self._bundle
            manifest = json.loads((self.model_dir / "manifest.json").read_text(encoding="utf-8"))
            if not isinstance(manifest, dict):
                raise ValueError("Invalid serving manifest")
            if manifest["model_version"] != MODEL_VERSION:
                raise ValueError("Unsupported serving version")
            validate_selection(manifest["selection"])
            digest = hashlib.sha256(json.dumps(manifest["selection"], sort_keys=True).encode()).hexdigest()
            if digest != manifest["selection_sha256"]:
                raise ValueError("Frozen selection digest mismatch")
            cutoff = baselines.parse_time(manifest["snapshot_cutoff"])
            catalog = set(manifest["catalog_ids"])

            def read(name, *, jsonl=False):
                path = self.model_dir / name
                expected = manifest["outputs"][name]
                if path.stat().st_size != expected["bytes"] or artifact_io.file_sha256(path) != expected["sha256"]:
                    raise ValueError(f"Invalid serving artifact: {name}")
                return baseline_replay._read_jsonl(path) if jsonl else json.loads(path.read_text(encoding="utf-8"))

            profiles = {}
            for profile in read("profiles.jsonl", jsonl=True):
                if not isinstance(profile, dict) or not isinstance(profile.get("positive_weights"), dict):
                    raise ValueError("Invalid serving profile object")
                user = profile["user_id"]
                count = profile["history_count"]
                seen = set(profile["seen_business_ids"])
                weights = profile["positive_weights"]
                if (not isinstance(user, str) or not user or user in profiles or type(count) is not int
                        or count < len(seen) or not seen <= catalog or not set(weights) <= seen
                        or set(profile["positive_business_ids"]) != set(weights)
                        or any(weight not in (1, 2) for weight in weights.values())
                        or baselines.parse_time(profile["as_of_time"]) != cutoff
                        or (profile["history_end_time"] and baselines.parse_time(profile["history_end_time"]) >= cutoff)):
                    raise ValueError("Invalid serving profile")
                profiles[user] = profile
            if len(profiles) != manifest["profile_count"]:
                raise ValueError("Serving profile count mismatch")
            disabled = []
            try:
                popularity = read("popularity.json")
                if not isinstance(popularity, dict) or set(popularity) != catalog or any(not math.isfinite(row["score"]) or row["score"] < 0 for row in popularity.values()):
                    raise ValueError("Invalid popularity model")
            except (OSError, ValueError, KeyError, TypeError):
                # CF/content still need a deterministic pool order, but this table
                # must never be exposed as a healthy popularity channel.
                popularity = {item: {"score": 0.0} for item in catalog}
                disabled.append("popularity")
            try:
                neighbors = read("neighbors.json")
                if not isinstance(neighbors, dict):
                    raise ValueError("Invalid neighbors object")
                if any(item not in catalog or any(row["business_id"] not in catalog or not math.isfinite(row["similarity"])
                                                  or not 0 <= row["similarity"] <= 1 for row in values)
                       for item, values in neighbors.items()):
                    raise ValueError("Invalid neighbors")
            except (OSError, ValueError, KeyError, TypeError):
                neighbors = {}
                disabled.append("itemcf")
            try:
                model = read("content.json")
                if not isinstance(model, dict) or not isinstance(model.get("item_vectors"), dict) or not isinstance(model.get("idf"), dict):
                    raise ValueError("Invalid content object")
                if model["cutoff"] != manifest["snapshot_cutoff"] or set(model["item_vectors"]) != catalog:
                    raise ValueError("Invalid content cutoff/catalog")
                if any(not isinstance(vector, dict) for vector in model["item_vectors"].values()):
                    raise ValueError("Invalid content vectors")
                if any(not math.isfinite(weight) or weight < 0 for vector in model["item_vectors"].values() for weight in vector.values()):
                    raise ValueError("Invalid content weights")
            except (OSError, ValueError, KeyError, TypeError):
                model = {"item_vectors": {}, "idf": {}}
                disabled.append("content")
            postings = defaultdict(list)
            for item, vector in sorted(model["item_vectors"].items()):
                for term, weight in vector.items():
                    postings[term].append((item, weight))
            self._bundle = {"manifest": manifest, "profiles": profiles, "popularity": popularity,
                            "neighbors": neighbors, "content": model, "postings": dict(postings),
                            "disabled_channels": tuple(disabled)}
            return self._bundle


class RequestRecallIndex(content.ContentIndex):
    """Use immutable shared model tables with fresh caches for every API request."""

    def __init__(self, bundle, businesses, request):
        manifest = bundle["manifest"]
        if set(manifest["catalog_ids"]) != set(businesses):
            raise ValueError("Model/business universe mismatch")
        self.businesses, self.request = businesses, request
        self.cutoff = manifest["snapshot_cutoff"]
        self.profiles, self.popularity, self.neighbors = bundle["profiles"], bundle["popularity"], bundle["neighbors"]
        self.item_vectors, self.idf, self._postings = bundle["content"]["item_vectors"], bundle["content"]["idf"], bundle["postings"]
        self._request_key, self._recommendations = None, {}
        self._pool = None

    def candidate_pool(self, user_id, *, radius_km=None, max_price_level=4):
        if self._pool is not None:
            return self._pool
        seen = set(self.profile(user_id)["seen_business_ids"])
        allowed, distances = set(), {}
        for item, business in self.businesses.items():
            price, coords = business.get("price_level"), baselines._coordinates(business)
            if (item in seen or not business.get("is_open") or business["city"].lower() != self.request.city.lower()
                    or price not in (1, 2, 3, 4) or price > self.request.max_price_level or coords is None):
                continue
            distance = baselines.distance_km(self.request.latitude, self.request.longitude, *coords)
            if distance <= self.request.radius_km:
                allowed.add(item)
                distances[item] = distance
        order = sorted(allowed, key=lambda item: (-self.popularity[item]["score"] / (1 + distances[item]), item))
        self._pool = allowed, order, distances
        return self._pool


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=Path("data/derived/tampa_full_reviews_v1"))
    parser.add_argument("--selection-dir", type=Path, default=Path("data/derived/fusion_v1"))
    parser.add_argument("--output-dir", type=Path, default=Path("data/derived/serving_v1"))
    args = parser.parse_args(argv)
    experiment = artifact_io.verify_artifacts(args.selection_dir, "experiment_manifest.json")
    selection = json.loads((args.selection_dir / "selection.json").read_text(encoding="utf-8"))
    digest = hashlib.sha256(json.dumps(selection, sort_keys=True).encode()).hexdigest()
    if digest != experiment["selection_sha256"]:
        raise ValueError("Frozen selection mismatch")
    for name, source in experiment["inputs"].items():
        if artifact_io.file_sha256(args.data_dir / name) != source["sha256"]:
            raise ValueError("Serving data differs from the selection experiment")
    manifest = build_serving_snapshot(args.data_dir, selection, args.output_dir,
                                      provenance={"fusion_manifest_sha256": artifact_io.file_sha256(args.selection_dir / "experiment_manifest.json"),
                                                  "validation_selection_sha256": digest})
    print(json.dumps({"snapshot_cutoff": manifest["snapshot_cutoff"], "profiles": manifest["profile_count"]}), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
