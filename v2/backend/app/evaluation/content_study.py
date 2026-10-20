"""Matched-target study of uncapped histories and category content retrieval."""

import argparse
import hashlib
import json
import math
import platform
import sys
import tempfile
from collections import Counter, defaultdict
from pathlib import Path

from app import artifact_io
from app.evaluation.baseline_replay import _eligibility_reason, _read_jsonl, _sha256
from app.retrieval.baselines import parse_time, validate_interactions
from app.retrieval.content import build_content_index


STUDY_ID = "fullcity_content_v1"
DEFAULT_CUTOFFS = ("2017-11-08 20:34:02", "2019-05-30 23:02:52")
ENGINES = ("popularity", "itemcf", "content", "combined", "combined_content")
GROUPS = ("all", "cold", "light", "warm")


class MetricAccumulator:
    """Retain counters and catalog coverage, not every request's candidate list."""

    def __init__(self):
        self.count = self.eligible = self.empty = self.candidate_count = 0
        self.hits = Counter()
        self.eligible_hits = Counter()
        self.ndcg = 0.0
        self.covered = set()

    def add(self, ids, target, *, eligible):
        rank = ids.index(target) + 1 if target in ids else None
        self.count += 1
        self.eligible += eligible
        self.empty += not ids
        self.candidate_count += len(ids)
        self.covered.update(ids[:100])
        for k in (10, 20, 100):
            hit = rank is not None and rank <= k
            self.hits[k] += hit
            self.eligible_hits[k] += eligible and hit
        if rank is not None and rank <= 10:
            self.ndcg += 1 / math.log2(rank + 1)
        return rank

    def result(self, *, catalog_size):
        def ratio(numerator, denominator):
            return numerator / denominator if denominator else None

        return {"requests": self.count, "eligible_requests": self.eligible,
                "recall@20": ratio(self.hits[20], self.count),
                "hit_rate@10": ratio(self.hits[10], self.count),
                "ndcg@10": ratio(self.ndcg, self.count),
                "recall@100": ratio(self.hits[100], self.count),
                "eligible_recall@20": ratio(self.eligible_hits[20], self.eligible),
                "eligible_recall@100": ratio(self.eligible_hits[100], self.eligible),
                "catalog_coverage@100": ratio(len(self.covered), catalog_size),
                "empty_recall_rate": ratio(self.empty, self.count),
                "mean_candidate_count": ratio(self.candidate_count, self.count)}


def _reference_queries(rows, cutoff, end):
    seen, counts = defaultdict(set), Counter()
    for row in rows:
        if row["event_time"] < cutoff:
            seen[row["user_id"]].add(row["business_id"])
            counts[row["user_id"]] += 1
    window = [row for row in rows if row["event_time"] >= cutoff and (end is None or row["event_time"] < end)]
    targets, repeated = {}, 0
    for row in window:
        if row["rating"] >= 4:
            user = row["user_id"]
            if row["business_id"] in seen[user]:
                repeated += 1
            else:
                targets.setdefault(user, {**row, "reference_history_count": counts[user],
                                         "reference_cohort": "cold" if not counts[user] else "light" if counts[user] < 5 else "warm"})
    ordered = [targets[user] for user in sorted(targets)]
    fingerprint = hashlib.sha256(json.dumps(ordered, sort_keys=True).encode()).hexdigest()
    users = {row["user_id"] for row in window}
    return ordered, {"requests": len(ordered), "target_fingerprint": fingerprint,
                     "window_events": len(window), "window_users": len(users),
                     "users_without_new_positive": len(users) - len(ordered),
                     "low_rating_events": sum(row["rating"] < 4 for row in window),
                     "repeated_positive_events": repeated}


def _evaluate_index(index, queries, reference, *, scenarios, trace_samples, progress=False):
    result = {}
    for scenario, radius in scenarios.items():
        accumulators = {engine: {group: MetricAccumulator() for group in GROUPS} for engine in ENGINES}
        reasons, cohorts, outcomes, complementarity = Counter(), Counter(), Counter(), Counter()
        candidate_digest = hashlib.sha256()
        audited = 0
        examples = Counter()
        for number, target in enumerate(queries, start=1):
            user, item = target["user_id"], target["business_id"]
            profile = index.profile(user)
            allowed, _, _ = index.candidate_pool(user, radius_km=radius)
            reason = _eligibility_reason(index, profile, item, allowed, radius)
            reasons[reason] += 1
            cohorts[profile["cohort"]] += 1
            trace = {"user_hash": hashlib.sha256(user.encode()).hexdigest()[:16],
                     "as_of_time": index.cutoff, "target_business_id": item,
                     "target_time": target["event_time"], "reference_cohort": target["reference_cohort"],
                     "model_history_cohort": profile["cohort"], "history_count": profile["history_count"],
                     "eligibility_reason": reason, "ranks": {}, "candidates": {}, "explanations": {}}
            seen = set(profile["seen_business_ids"])
            assert profile["history_end_time"] is None or profile["history_end_time"] < index.cutoff
            for engine in ENGINES:
                recs = index.recommend(user, engine, radius_km=radius)
                ids = [row["business_id"] for row in recs]
                if len(ids) != len(set(ids)) or len(ids) > 100 or not set(ids) <= allowed or set(ids) & seen:
                    raise AssertionError("Candidate eligibility, deduplication or seen-exclusion violation")
                audited += len(ids)
                rank = accumulators[engine]["all"].add(ids, item, eligible=reason == "eligible")
                accumulators[engine][target["reference_cohort"]].add(ids, item, eligible=reason == "eligible")
                trace["ranks"][engine], trace["candidates"][engine] = rank, ids
                trace["explanations"][engine] = recs[:3]
            candidate_digest.update(json.dumps({"user": trace["user_hash"], "target": item,
                                                 "candidates": trace["candidates"]}, sort_keys=True).encode())
            rank = trace["ranks"]["combined_content"]
            outcome = reason if reason != "eligible" else (
                "hit@20" if rank is not None and rank <= 20 else "rank_21_to_100" if rank else "eligible_but_not_recalled")
            outcomes[outcome] += 1
            old_hit = trace["ranks"]["combined"] is not None
            content_hit = trace["ranks"]["content"] is not None
            new_hit = rank is not None
            complementarity["content_only" if content_hit and not old_hit else "combined_only" if old_hit and not content_hit
                            else "both" if old_hit and content_hit else "neither"] += 1
            complementarity["gained_by_threeway"] += new_hit and not old_hit
            complementarity["lost_by_threeway"] += old_hit and not new_hit
            sample_key = "content_gain" if content_hit and not old_hit else outcome
            if examples[sample_key] < 2:
                examples[sample_key] += 1
                trace_samples.append({"scenario": scenario, **trace})
            if progress and number % 10000 == 0:
                print(f"  {scenario}: {number:,}/{len(queries):,} requests", flush=True)
        result[scenario] = {
            "requests": len(queries), "target_fingerprint": reference["target_fingerprint"],
            "eligible_targets": reasons["eligible"],
            "target_eligibility_rate": reasons["eligible"] / len(queries) if queries else None,
            "eligibility_reasons": dict(sorted(reasons.items())),
            "model_history_cohorts": dict(sorted(cohorts.items())),
            "constraint_violations": 0, "candidate_appearances_audited": audited,
            "candidate_digest": candidate_digest.hexdigest(),
            "combined_content_outcomes": dict(sorted(outcomes.items())),
            "content_complementarity@100": dict(sorted(complementarity.items())),
            "engines": {engine: {group: acc.result(catalog_size=len(index.visible_business_ids))
                                  for group, acc in groups.items()} for engine, groups in accumulators.items()},
        }
    return result


def evaluate_study(legacy_interactions, full_interactions, businesses, *, cutoffs=DEFAULT_CUTOFFS, progress=False):
    legacy = validate_interactions(legacy_interactions, businesses)
    full = validate_interactions(full_interactions, businesses)
    full_by_id = {row["interaction_id"]: row for row in full}
    if not legacy or any(full_by_id.get(row["interaction_id"]) != row for row in legacy):
        raise ValueError("Legacy interactions must be a consistent subset of full-city data")
    if len(cutoffs) != 2:
        raise ValueError("Two cutoffs required")
    first, second = [parse_time(value).isoformat(sep=" ") for value in cutoffs]
    if not full[0]["event_time"] < first < second <= full[-1]["event_time"]:
        raise ValueError("Cutoffs must create nonempty, ordered full-city windows")
    query_sets, references = {}, {}
    for split, cutoff, end in (("validation", first, second), ("test", second, None)):
        query_sets[split], references[split] = _reference_queries(full, cutoff, end)
        if not references[split]["window_events"]:
            raise ValueError("Empty evaluation window")
    report = {"study_id": STUDY_ID, "config": {
        "cutoffs": [first, second], "candidate_limit": 100, "neighbor_limit": 50, "shrinkage": 5,
        "radius_km": 10, "cohort_basis": "common full-history cohort at cutoff",
        "label_policy": "shared full-data first high-rating unseen-at-cutoff merchant per window",
        "content_policy": "category TF-IDF cosine, positive-history weighted, inverse price difference",
        "catalog_warning": "snapshot_catalog assumes all snapshot merchant metadata was already known; conditional only",
    }, "data": {"legacy_interactions": len(legacy), "full_interactions": len(full),
                 "legacy_users": len({row["user_id"] for row in legacy}),
                 "full_users": len({row["user_id"] for row in full}), "businesses": len(businesses)},
        "common_targets": references, "variants": {}}
    artifacts = {"models": {}, "traces": [], "queries": []}
    for split, queries in query_sets.items():
        artifacts["queries"].extend({"split": split, **row} for row in queries)
    for variant, rows, policy in (("legacy_history", legacy, "historical"),
                                  ("full_history", full, "historical"),
                                  ("full_snapshot_catalog", full, "snapshot_catalog")):
        report["variants"][variant] = {}
        for split, cutoff in (("validation", first), ("test", second)):
            if progress:
                print(f"Building {variant}/{split}, cutoff={cutoff}", flush=True)
            index = build_content_index(rows, businesses, cutoff, catalog_policy=policy)
            artifacts["models"][f"{variant}_{split}"] = index.content_model()
            samples = []
            scenarios = {"city_preference": None}
            if policy == "historical":
                scenarios["simulated_geo"] = 10.0
            evaluated = _evaluate_index(index, query_sets[split], references[split], scenarios=scenarios,
                                        trace_samples=samples, progress=progress)
            artifacts["traces"].extend({"variant": variant, "split": split, **trace} for trace in samples)
            report["variants"][variant][split] = {
                "cutoff": cutoff, "catalog_policy": policy, "strict_historical_catalog": policy == "historical",
                "history_events": len(index.history), "history_users": len(index.profiles),
                "historical_catalog_size": len(index.historical_business_ids),
                "candidate_catalog_size": len(index.visible_business_ids), "scenarios": evaluated}
            del index
    return report, artifacts


def render_report(report):
    lines = ["# 完整城市交互与内容召回对照报告", "",
             "共同目标固定于完整数据；旧历史/完整历史主实验使用历史可见商户，辅助snapshot实验假设全部商户资料预先可见。",
             "分群固定为完整历史截止点分组；model_history_cohorts另外报告各模型实际历史缺失情况。", "",
             "```json", json.dumps({"config": report["config"], "data": report["data"],
                                      "common_targets": report["common_targets"]}, ensure_ascii=False, indent=2), "```", "",
             "| variant | split | scenario | engine | cohort | n | eligible | R20 | N10 | R100 | coverage100 |",
             "|---|---|---|---|---|---:|---:|---:|---:|---:|---:|"]
    for variant, splits in report["variants"].items():
        for split, data in splits.items():
            for scenario, values in data["scenarios"].items():
                for engine, groups in values["engines"].items():
                    for cohort, metric in groups.items():
                        formatted = " | ".join("NA" if metric[key] is None else f"{metric[key]:.6f}"
                                               for key in ("recall@20", "ndcg@10", "recall@100", "catalog_coverage@100"))
                        lines.append(f"| {variant} | {split} | {scenario} | {engine} | {cohort} | {metric['requests']} | {metric['eligible_requests']} | {formatted} |")
                lines += ["", f"### {variant} / {split} / {scenario}", "", "```json",
                          json.dumps({key: value for key, value in values.items() if key != "engines"},
                                     ensure_ascii=False, indent=2), "```", ""]
    lines += ["## 解释边界", "",
              "- 与上一阶段原生目标不同，不能直接用上一阶段指标声称采样修复收益；本报告旧/新历史使用相同的完整数据共同目标。",
              "- 历史可见性、模型用户历史和热门统计随输入改变；该对照衡量整体采样策略影响，不单独识别某个因素的因果效应。",
              "- 历史可见商户仍以第一条评论为代理；静态类别/价格/坐标无法恢复历史变动。",
              "- snapshot_catalog只是假设商户元数据预先已知的条件实验，不视为严格历史无泄漏效果；不使用未来评分或评论文本。",
              "- 内容通道为类别TF-IDF与价格匹配，未训练语义Embedding；没有历史的用户不凭空生成偏好。",
              "- 所有模型参数固定，未根据测试集调参；交替合并不是RRF，不保证优于单路。",
              "- 全量请求做候选约束与顺序摘要审计，trace文件仅为分原因样本，不是全部请求。", ""]
    return "\n".join(lines)


def run_study(legacy_dir, full_dir, output_dir, *, cutoffs=DEFAULT_CUTOFFS, progress=False):
    legacy_dir, full_dir, output_dir = [Path(path).resolve() for path in (legacy_dir, full_dir, output_dir)]
    for source in (legacy_dir, full_dir):
        if source == output_dir or source in output_dir.parents or output_dir in source.parents:
            raise ValueError("Output must be separate from source directories")
    manifest_path = output_dir / "study_manifest.json"
    if output_dir.exists() and any(output_dir.iterdir()):
        if not manifest_path.exists() or json.loads(manifest_path.read_text(encoding="utf-8")).get("study_id") != STUDY_ID:
            raise ValueError("Refusing unrelated output directory")
    if (full_dir / "data_manifest.json").exists():
        artifact_io.verify_artifacts(full_dir, "data_manifest.json")
    inputs = {f"{label}:{name}": directory / name for label, directory in (("legacy", legacy_dir), ("full", full_dir))
              for name in ("businesses.jsonl", "interactions.jsonl")}
    hashes = {key: _sha256(path) for key, path in inputs.items()}
    if hashes["legacy:businesses.jsonl"] != hashes["full:businesses.jsonl"]:
        raise ValueError("Business universe must be byte-identical for this sampling comparison")
    business_rows = _read_jsonl(full_dir / "businesses.jsonl")
    businesses = {row["business_id"]: row for row in business_rows}
    if len(businesses) != len(business_rows):
        raise ValueError("Duplicate business IDs")
    report, artifacts = evaluate_study(_read_jsonl(legacy_dir / "interactions.jsonl"),
                                      _read_jsonl(full_dir / "interactions.jsonl"), businesses,
                                      cutoffs=cutoffs, progress=progress)
    if hashes != {key: _sha256(path) for key, path in inputs.items()}:
        raise RuntimeError("Input changed during study")
    from app.retrieval import baselines, content
    from app.evaluation import baseline_replay

    manifest = {"study_id": STUDY_ID, "config": report["config"],
                "inputs": {key: {"sha256": hashes[key], "bytes": path.stat().st_size} for key, path in inputs.items()},
                "code_sha256": {Path(module).name: _sha256(Path(module))
                                for module in (__file__, baselines.__file__, content.__file__,
                                               baseline_replay.__file__, artifact_io.__file__)},
                "environment": {"python": platform.python_version(), "platform": platform.platform(),
                                "dependencies": "Python standard library"},
                "artifact_counts": {key: len(value) for key, value in artifacts.items()}}
    output_dir.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".content-study-", dir=output_dir.parent) as temporary:
        stage = Path(temporary)
        for name, data in (("metrics.json", report), ("content_models.json", artifacts["models"])):
            (stage / name).write_text(json.dumps(data, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
        for name, key in (("trace_samples.jsonl", "traces"), ("target_queries.jsonl", "queries")):
            with (stage / name).open("w", encoding="utf-8") as out:
                for row in artifacts[key]:
                    out.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
        (stage / "report.md").write_text(render_report(report), encoding="utf-8")
        artifact_io.publish_directory(stage, output_dir, manifest, "study_manifest.json")
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--legacy-dir", type=Path, default=Path("data/processed"))
    parser.add_argument("--full-dir", type=Path, default=Path("data/derived/tampa_full_reviews_v1"))
    parser.add_argument("--output-dir", type=Path, default=Path("data/derived/fullcity_content_v1"))
    parser.add_argument("--validation-cutoff", default=DEFAULT_CUTOFFS[0])
    parser.add_argument("--test-cutoff", default=DEFAULT_CUTOFFS[1])
    args = parser.parse_args(argv)
    result = run_study(args.legacy_dir, args.full_dir, args.output_dir,
                       cutoffs=(args.validation_cutoff, args.test_cutoff), progress=True)
    print(json.dumps({"study_id": result["study_id"], "data": result["data"]}), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
