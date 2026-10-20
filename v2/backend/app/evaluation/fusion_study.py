"""Validation-only fusion selection followed by frozen iterative-test evaluation."""

import argparse
import copy
import hashlib
import json
import platform
import tempfile
from collections import Counter
from pathlib import Path

from app import artifact_io
from app.evaluation import baseline_replay, content_study
from app.evaluation.content_study import DEFAULT_CUTOFFS, GROUPS, MetricAccumulator, _reference_queries
from app.ranking import fusion
from app.retrieval import baselines, content


EXPERIMENT_ID = "fusion_v1"
CHANNELS = ("popularity", "itemcf", "content")


def configurations():
    result = {}

    def add(name, weights, k=60, budgets=None):
        result[name] = {"name": name, "mode": "rrf", "k": k,
                        "weights": dict(zip(CHANNELS, weights)),
                        "budgets": budgets or dict.fromkeys(CHANNELS, 100)}

    add("popularity", (1, 0, 0))
    add("itemcf", (0, 1, 0))
    add("content", (0, 0, 1))
    add("rrf_dual", (1, 1, 0))
    add("rrf_triple", (1, 1, 1))
    add("weighted_cf025", (1, .25, 0))
    add("weighted_cf050", (1, .5, 0))
    add("weighted_content010", (1, 1, .1))
    add("weighted_content025", (1, 1, .25))
    add("weighted_cf050_content010", (1, .5, .1))
    add("rrf_dual_k10", (1, 1, 0), k=10)
    add("weighted_content_budget20", (1, 1, .25), budgets={"popularity": 100, "itemcf": 100, "content": 20})
    for name, mode in (("dual_alternate", "combined"), ("triple_alternate", "combined_content")):
        result[name] = {"name": name, "mode": mode}
    return result


def choose_config(metrics, configs):
    eligible = [name for name in metrics if configs[name]["mode"] == "rrf"]

    def key(name):
        row = metrics[name]["all"]
        return tuple(-(row[metric] or 0) for metric in ("ndcg@10", "recall@20", "recall@100")) + (name,)

    return copy.deepcopy(configs[min(eligible, key=key)])


def rank_configuration(index, user, channels, config, allowed, radius):
    if config["mode"] != "rrf":
        return index.recommend(user, config["mode"], radius_km=radius)
    return fusion.fuse_rrf(channels, weights=config["weights"], k=config["k"],
                           budgets=config["budgets"], allowed=allowed)


def _evaluate(index, queries, configs_by_scenario, progress):
    scenarios, samples = {}, []
    for scenario, configs in configs_by_scenario.items():
        radius = None if scenario == "city_preference" else 10.0
        counters = {name: {group: MetricAccumulator() for group in GROUPS} for name in configs}
        digest = hashlib.sha256()
        reasons, unique_hits, retained_hits, lost_hits = Counter(), Counter(), Counter(), Counter()
        audits = 0
        example_counts = Counter()
        for number, target in enumerate(queries, start=1):
            user, item = target["user_id"], target["business_id"]
            profile = index.profile(user)
            allowed, _, _ = index.candidate_pool(user, radius_km=radius)
            reason = baseline_replay._eligibility_reason(index, profile, item, allowed, radius)
            reasons[reason] += 1
            channels = {name: index.recommend(user, name, radius_km=radius) for name in CHANNELS}
            channel_hits = {name: item in {row["business_id"] for row in recs} for name, recs in channels.items()}
            exclusive = {name for name in CHANNELS if channel_hits[name] and sum(channel_hits.values()) == 1}
            unique_hits.update(exclusive)
            trace = {"user_hash": hashlib.sha256(user.encode()).hexdigest()[:16],
                     "target_business_id": item, "target_time": target["event_time"],
                     "as_of_time": index.cutoff, "scenario": scenario,
                     "eligibility_reason": reason, "ranks": {}}
            rankings = {}
            for name, config in configs.items():
                recs = rank_configuration(index, user, channels, config, allowed, radius)
                ids = [row["business_id"] for row in recs]
                if len(ids) > 100 or len(ids) != len(set(ids)) or not set(ids) <= allowed:
                    raise AssertionError("Fusion candidate contract violated")
                audits += len(ids)
                rank = counters[name]["all"].add(ids, item, eligible=reason == "eligible")
                counters[name][target["reference_cohort"]].add(ids, item, eligible=reason == "eligible")
                trace["ranks"][name], rankings[name] = rank, ids
                for channel in exclusive:
                    (retained_hits if rank is not None else lost_hits)[f"{name}:{channel}"] += 1
            digest.update(json.dumps({"user": trace["user_hash"], "candidates": rankings}, sort_keys=True).encode())
            example_key = next(iter(sorted(exclusive)), reason)
            if example_counts[example_key] < 2:
                example_counts[example_key] += 1
                samples.append(trace)
            if progress and number % 10000 == 0:
                print(f"  {scenario}: {number:,}/{len(queries):,}", flush=True)
        scenarios[scenario] = {
            "requests": len(queries), "eligible_targets": reasons["eligible"],
            "eligibility_reasons": dict(sorted(reasons.items())), "candidate_digest": digest.hexdigest(),
            "candidate_appearances_audited": audits, "constraint_violations": 0,
            "exclusive_channel_hits@100": dict(sorted(unique_hits.items())),
            "exclusive_hits_retained@100": dict(sorted(retained_hits.items())),
            "exclusive_hits_lost@100": dict(sorted(lost_hits.items())),
            "engines": {name: {group: value.result(catalog_size=len(index.visible_business_ids))
                                for group, value in groups.items()} for name, groups in counters.items()},
        }
    return {"cutoff": index.cutoff, "history_events": len(index.history), "scenarios": scenarios}, samples


def evaluate_fusion(interactions, businesses, *, cutoffs=DEFAULT_CUTOFFS, freeze_callback=None, progress=False):
    rows = baselines.validate_interactions(interactions, businesses)
    first, second = [baselines.parse_time(value).isoformat(sep=" ") for value in cutoffs]
    if not rows or not rows[0]["event_time"] < first < second <= rows[-1]["event_time"]:
        raise ValueError("Invalid fusion study windows")
    configs = configurations()
    if progress:
        print("Building validation index", flush=True)
    index = content.build_content_index(rows, businesses, first)
    queries, reference = _reference_queries(rows, first, second)
    if not queries:
        raise ValueError("No validation targets")
    validation, samples = _evaluate(index, queries, {scenario: configs for scenario in ("city_preference", "simulated_geo")}, progress)
    selection = {scenario: choose_config(value["engines"], configs)
                 for scenario, value in validation["scenarios"].items()}
    frozen_bytes = json.dumps(selection, sort_keys=True).encode()
    if freeze_callback:
        freeze_callback(copy.deepcopy(selection))
    del index
    if progress:
        print("Selection frozen; building iterative-test index", flush=True)
    index = content.build_content_index(rows, businesses, second)
    queries, test_reference = _reference_queries(rows, second, None)
    test_configs = {scenario: {name: configs[name] for name in dict.fromkeys(
        ("popularity", "dual_alternate", chosen["name"]))} for scenario, chosen in selection.items()}
    test, test_samples = _evaluate(index, queries, test_configs, progress)
    if frozen_bytes != json.dumps(selection, sort_keys=True).encode():
        raise AssertionError("Selection changed after reading test results")
    report = {"experiment_id": EXPERIMENT_ID, "test_is_iterative": True,
              "selection_policy": "validation NDCG@10, Recall@20, Recall@100, stable name; no test tuning",
              "configs": configs, "selection": selection,
              "selection_sha256": hashlib.sha256(frozen_bytes).hexdigest(),
              "target_references": {"validation": reference, "test": test_reference},
              "validation": validation, "test": test}
    return report, [{"split": "validation", **row} for row in samples] + [{"split": "test", **row} for row in test_samples]


def render_report(report):
    lines = ["# 融合优化实验报告", "", "配置仅在validation选择并冻结，随后运行迭代test。已有test已多次查看，不是盲测。", "",
             "```json", json.dumps(report["selection"], ensure_ascii=False, indent=2), "```", "",
             "| split | scenario | method | cohort | n | Recall20 | NDCG10 | Recall100 |",
             "|---|---|---|---|---:|---:|---:|---:|"]
    for split in ("validation", "test"):
        for scenario, summary in report[split]["scenarios"].items():
            for engine, groups in summary["engines"].items():
                for group, metrics in groups.items():
                    values = " | ".join("NA" if metrics[key] is None else f"{metrics[key]:.6f}" for key in ("recall@20", "ndcg@10", "recall@100"))
                    lines.append(f"| {split} | {scenario} | {engine} | {group} | {metrics['requests']} | {values} |")
    lines += ["", "## 边界", "", "预算100、历史商户可见、全局冻结画像，模拟位置非真实请求。单目标Recall等于命中率。", "",
              "validation比较全部预先声明配置；test只评估热门、旧双路和冻结选择。没有LightGBM/语义查询/实时画像或线上收益结论。", ""]
    return "\n".join(lines)


def run_fusion_study(data_dir, output_dir, *, cutoffs=DEFAULT_CUTOFFS, progress=False):
    data_dir, output_dir = Path(data_dir).resolve(), Path(output_dir).resolve()
    if data_dir == output_dir or data_dir in output_dir.parents or output_dir in data_dir.parents:
        raise ValueError("Output must be separate from input")
    if output_dir.exists() and any(output_dir.iterdir()):
        manifest_path = output_dir / "experiment_manifest.json"
        if not manifest_path.exists() or json.loads(manifest_path.read_text(encoding="utf-8")).get("experiment_id") != EXPERIMENT_ID:
            raise ValueError("Unrelated output directory")
    if (data_dir / "data_manifest.json").exists():
        artifact_io.verify_artifacts(data_dir, "data_manifest.json")
    paths = [data_dir / name for name in ("businesses.jsonl", "interactions.jsonl")]
    hashes = {path.name: artifact_io.file_sha256(path) for path in paths}
    business_rows = baseline_replay._read_jsonl(paths[0])
    businesses = {row["business_id"]: row for row in business_rows}
    if len(businesses) != len(business_rows):
        raise ValueError("Duplicate businesses")
    output_dir.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".fusion-", dir=output_dir.parent) as temporary:
        stage = Path(temporary)

        def freeze(selection):
            (stage / "selection.json").write_text(json.dumps(selection, sort_keys=True, indent=2) + "\n", encoding="utf-8")

        report, traces = evaluate_fusion(baseline_replay._read_jsonl(paths[1]), businesses, cutoffs=cutoffs, freeze_callback=freeze, progress=progress)
        if hashes != {path.name: artifact_io.file_sha256(path) for path in paths}:
            raise RuntimeError("Inputs changed during fusion study")
        manifest = {"experiment_id": EXPERIMENT_ID, "selection_sha256": report["selection_sha256"],
                    "inputs": {path.name: {"sha256": hashes[path.name], "bytes": path.stat().st_size} for path in paths},
                    "code_sha256": {Path(module).name: artifact_io.file_sha256(module) for module in (
                        __file__, fusion.__file__, content.__file__, baselines.__file__, baseline_replay.__file__, content_study.__file__, artifact_io.__file__)},
                    "environment": {"python": platform.python_version(), "platform": platform.platform()}}
        (stage / "metrics.json").write_text(json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
        (stage / "trace_samples.jsonl").write_text("".join(json.dumps(row, sort_keys=True) + "\n" for row in traces), encoding="utf-8")
        (stage / "report.md").write_text(render_report(report), encoding="utf-8")
        artifact_io.publish_directory(stage, output_dir, manifest, "experiment_manifest.json")
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=Path("data/derived/tampa_full_reviews_v1"))
    parser.add_argument("--output-dir", type=Path, default=Path("data/derived/fusion_v1"))
    parser.add_argument("--validation-cutoff", default=DEFAULT_CUTOFFS[0])
    parser.add_argument("--test-cutoff", default=DEFAULT_CUTOFFS[1])
    args = parser.parse_args(argv)
    report = run_fusion_study(args.data_dir, args.output_dir, cutoffs=(args.validation_cutoff, args.test_cutoff), progress=True)
    print(json.dumps(report["selection"], ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
