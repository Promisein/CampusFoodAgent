"""Global frozen-window next-positive evaluation; never force targets into recall."""

import argparse
import hashlib
import json
import math
import platform
import sys
from collections import Counter
from pathlib import Path

from app.retrieval.baselines import build_index, parse_time, validate_interactions


ENGINES = ("popularity", "itemcf", "combined")
COHORTS = ("all", "cold", "light", "warm")
EXPERIMENT_ID = "baseline_recall_v1"


def summarize_metrics(observations, *, catalog_size):
    count = len(observations)
    eligible = [row for row in observations if row["eligible"]]

    def hit(row, k):
        return row["rank"] is not None and row["rank"] <= k

    def mean(values, denominator):
        return sum(values) / denominator if denominator else None

    covered = {item for row in observations for item in row["candidates"][:100]}
    return {
        "requests": count, "eligible_requests": len(eligible),
        "recall@20": mean((hit(row, 20) for row in observations), count),
        "hit_rate@10": mean((hit(row, 10) for row in observations), count),
        "ndcg@10": mean((1 / math.log2(row["rank"] + 1) if hit(row, 10) else 0
                         for row in observations), count),
        "recall@100": mean((hit(row, 100) for row in observations), count),
        "eligible_recall@20": mean((hit(row, 20) for row in eligible), len(eligible)),
        "eligible_recall@100": mean((hit(row, 100) for row in eligible), len(eligible)),
        "catalog_coverage@100": len(covered) / catalog_size if catalog_size else None,
        "empty_recall_rate": mean((not row["candidates"] for row in observations), count),
        "mean_candidate_count": mean((len(row["candidates"]) for row in observations), count),
    }


def _select_targets(rows, index, end):
    window = [row for row in rows if row["event_time"] >= index.cutoff
              and (end is None or row["event_time"] < end)]
    targets, repeated = {}, 0
    for row in window:
        if row["rating"] < 4:
            continue
        user, item = row["user_id"], row["business_id"]
        if item in index.profile(user)["seen_business_ids"]:
            repeated += 1
            continue
        targets.setdefault(user, row)
    users = {row["user_id"] for row in window}
    return targets, {
        "events": len(window), "users": len(users), "target_users": len(targets),
        "users_without_new_positive": len(users) - len(targets),
        "low_rating_events": sum(row["rating"] < 4 for row in window),
        "repeated_positive_events": repeated,
    }


def _eligibility_reason(index, profile, item, allowed, radius):
    if item not in index.visible_business_ids:
        return "not_in_historical_catalog"
    if radius is not None:
        if profile["geo_center"] is None:
            return "no_history_position"
        if index.businesses[item].get("price_level") not in (1, 2, 3, 4):
            return "unknown_price"
        if item not in allowed:
            return "outside_radius_or_missing_coordinates"
    return "eligible" if item in allowed else "excluded_seen_item"


def evaluate_dataset(interactions, businesses, *, candidate_limit=100, radius_km=10.0,
                     neighbor_limit=50, shrinkage=5.0, cutoffs=None):
    if candidate_limit < 100 or not math.isfinite(radius_km) or radius_km <= 0:
        raise ValueError("candidate_limit must be >=100 and radius_km positive/finite")
    rows = validate_interactions(interactions, businesses)
    if len(rows) < 5:
        raise ValueError("At least five interactions are needed for three nonempty windows")
    if cutoffs is None:
        cutoffs = (rows[int(len(rows) * 0.6)]["event_time"], rows[int(len(rows) * 0.8)]["event_time"])
    if len(cutoffs) != 2:
        raise ValueError("Exactly two cutoffs are required")
    first, second = [parse_time(value).isoformat(sep=" ") for value in cutoffs]
    if not rows[0]["event_time"] < first < second <= rows[-1]["event_time"]:
        raise ValueError("Cutoffs must produce ordered, nonempty history/validation/test windows")
    if not any(first <= row["event_time"] < second for row in rows):
        raise ValueError("Empty validation window")
    config = {
        "candidate_limit": candidate_limit, "radius_km": radius_km,
        "neighbor_limit": neighbor_limit, "shrinkage": shrinkage,
        "cutoffs": [first, second], "positive_rating_threshold": 4,
        "split_policy": "global frozen windows; all same-timestamp events are outside history",
        "target_policy": "first high-rating unseen-at-cutoff item per user per window",
        "merge_policy": "alternate itemcf/popularity, deduplicate, truncate; no RRF",
    }
    report = {"experiment_id": EXPERIMENT_ID, "config": config, "splits": {}}
    artifacts = {"profiles": [], "neighbors": [], "traces": []}
    for split, cutoff, end in (("validation", first, second), ("test", second, None)):
        index = build_index(rows, businesses, cutoff, neighbor_limit=neighbor_limit, shrinkage=shrinkage)
        targets, window = _select_targets(rows, index, end)
        split_report = {
            "cutoff": cutoff, "window_end_exclusive": end,
            "history_events": len(index.history), "history_users": len(index.profiles),
            "historical_catalog_size": len(index.visible_business_ids),
            "window": window, "scenarios": {},
        }
        for user in sorted(set(index.profiles) | set(targets)):
            artifacts["profiles"].append({"split": split, **index.profile(user)})
        for item, neighbors in sorted(index.neighbors.items()):
            artifacts["neighbors"].append({"split": split, "cutoff": cutoff,
                                           "business_id": item, "neighbors": neighbors})
        for scenario, radius in (("city_preference", None), ("simulated_geo", radius_km)):
            observations = {engine: {cohort: [] for cohort in COHORTS} for engine in ENGINES}
            complementarity = {key: 0 for key in ("popularity_only", "itemcf_only", "both", "neither")}
            reasons, no_position, violations = Counter(), 0, 0
            outcomes, example_counts, examples = Counter(), Counter(), []
            for user, target in sorted(targets.items()):
                profile = index.profile(user)
                allowed, _, _ = index.candidate_pool(user, radius_km=radius)
                reason = _eligibility_reason(index, profile, target["business_id"], allowed, radius)
                reasons[reason] += 1
                no_position += radius is not None and profile["geo_center"] is None
                trace = {
                    "split": split, "scenario": scenario,
                    "user_hash": hashlib.sha256(user.encode()).hexdigest()[:16],
                    "as_of_time": cutoff, "target_time": target["event_time"],
                    "target_business_id": target["business_id"], "cohort": profile["cohort"],
                    "history_count": profile["history_count"],
                    "eligible": reason == "eligible", "eligibility_reason": reason,
                    "candidate_pool_size": len(allowed), "candidates": {},
                    "target_ranks": {}, "top5_explanations": {},
                }
                for engine in ENGINES:
                    recommendations = index.recommend(user, engine, limit=candidate_limit, radius_km=radius)
                    ids = [rec["business_id"] for rec in recommendations]
                    violations += len(set(ids) - allowed)
                    if len(ids) != len(set(ids)):
                        raise AssertionError("Duplicate candidates")
                    rank = ids.index(target["business_id"]) + 1 if target["business_id"] in ids else None
                    observation = {"rank": rank, "eligible": reason == "eligible", "candidates": ids}
                    observations[engine]["all"].append(observation)
                    observations[engine][profile["cohort"]].append(observation)
                    trace["candidates"][engine] = ids
                    trace["target_ranks"][engine] = rank
                    trace["top5_explanations"][engine] = recommendations[:5]
                pop_hit = trace["target_ranks"]["popularity"] is not None and trace["target_ranks"]["popularity"] <= 100
                cf_hit = trace["target_ranks"]["itemcf"] is not None and trace["target_ranks"]["itemcf"] <= 100
                key = "both" if pop_hit and cf_hit else "popularity_only" if pop_hit else "itemcf_only" if cf_hit else "neither"
                complementarity[key] += 1
                combined_rank = trace["target_ranks"]["combined"]
                outcome = reason if reason != "eligible" else (
                    "hit@20" if combined_rank is not None and combined_rank <= 20
                    else "rank_21_to_100" if combined_rank is not None and combined_rank <= 100
                    else "eligible_but_not_recalled")
                outcomes[outcome] += 1
                if outcome != "hit@20" and example_counts[outcome] < 2:
                    example_counts[outcome] += 1
                    examples.append({key: trace[key] for key in (
                        "user_hash", "target_business_id", "cohort", "history_count",
                        "as_of_time", "target_time", "eligibility_reason", "target_ranks")})
                artifacts["traces"].append(trace)
            split_report["scenarios"][scenario] = {
                "requests": len(targets), "eligible_targets": reasons["eligible"],
                "target_eligibility_rate": reasons["eligible"] / len(targets) if targets else None,
                "requests_without_position": no_position, "eligibility_reasons": dict(sorted(reasons.items())),
                "constraint_violations": violations, "complementarity@100": complementarity,
                "combined_outcomes": dict(sorted(outcomes.items())), "failure_examples": examples,
                "engines": {engine: {cohort: summarize_metrics(observations[engine][cohort],
                                                               catalog_size=len(index.visible_business_ids))
                                     for cohort in COHORTS} for engine in ENGINES},
            }
            if violations:
                raise AssertionError("Candidates violated the allowed pool")
        report["splits"][split] = split_report
    return report, artifacts


def render_report(report):
    lines = [
        "# 画像感知基线召回实验报告", "",
        "本报告由真实离线回放自动生成。单目标下Recall等于命中率；总体指标包含不可召回目标，不强插正样本。",
        "地理实验位置是截止点历史坐标均值，非真实请求位置；无历史位置返回空候选。", "",
        "## 配置", "", "```json", json.dumps(report["config"], ensure_ascii=False, indent=2), "```", "",
        "## 时间和样本", "",
        "| split | cutoff | 历史交互 | 历史商户 | 窗口用户 | 正目标用户 | 无新高分目标用户 |",
        "|---|---|---:|---:|---:|---:|---:|",
    ]
    for split, data in report["splits"].items():
        window = data["window"]
        lines.append(f"| {split} | {data['cutoff']} | {data['history_events']} | {data['historical_catalog_size']} | {window['users']} | {window['target_users']} | {window['users_without_new_positive']} |")
    lines += ["", "## 总体与分群指标", "",
              "R20=Recall@20；N10=NDCG@10；R100=Recall@100。Coverage分母为各截止点完整历史商户库。", "",
              "| split | scenario | engine | cohort | n | eligible | R20 | N10 | R100 | Coverage100 | empty |",
              "|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|"]

    def fmt(value):
        return "NA" if value is None else f"{value:.6f}"

    for split, data in report["splits"].items():
        for scenario, scenario_data in data["scenarios"].items():
            for engine, groups in scenario_data["engines"].items():
                for cohort, metrics in groups.items():
                    values = " | ".join(fmt(metrics[key]) for key in (
                        "recall@20", "ndcg@10", "recall@100", "catalog_coverage@100", "empty_recall_rate"))
                    lines.append(f"| {split} | {scenario} | {engine} | {cohort} | {metrics['requests']} | {metrics['eligible_requests']} | {values} |")
    lines += ["", "## 资格覆盖和通道互补", ""]
    for split, data in report["splits"].items():
        for scenario, values in data["scenarios"].items():
            lines += [f"### {split} / {scenario}", "",
                      f"目标资格：{values['eligible_targets']}/{values['requests']}；无位置请求：{values['requests_without_position']}；约束越界：{values['constraint_violations']}。", "",
                      "```json", json.dumps({"eligibility_reasons": values["eligibility_reasons"],
                                              "complementarity@100": values["complementarity@100"],
                                              "combined_outcomes": values["combined_outcomes"],
                                              "failure_examples": values["failure_examples"]},
                                             ensure_ascii=False, indent=2), "```", ""]
    lines += ["## 局限与解释", "",
              "- 使用当前限量processed子集，商户每家最多40条交互、原文件顺序截断可能改变共现关系；不推断全量Yelp效果。",
              "- 不使用快照stars/review_count/is_open作为历史特征；商户首次历史评论仅是可见性代理，不是实际开业日期。",
              "- 类别、价格、坐标来自下载快照，无法恢复全部历史变动；simulated_geo为独立敏感性实验。",
              "- 无真实曝光、搜索词、请求位置；评测的是固定窗口内首个新商户高分目标，不是CTR或实时下一次就餐预测。",
              "- 低星目标、重复访问、窗口内无新高分目标用户不进入正目标集合，筛选数量见窗口统计；目标资格不满足仍计总体未命中。",
              "- ItemCF为空时纯协同通道保持空，combined通过热门补充；交替合并不是RRF，未训练LightGBM。",
              "- 测试历史可使用验证窗口已发生交互；所有配置固定，未按测试结果调参；重复用户跨窗口是时间回放设计。",
              "- 画像类别/价格字段已输出供后续内容模型使用；本阶段ItemCF仅使用历史正向种子与评分权重，地理通道使用历史中心。",
              "- 单路Top100的并集可达200；combined固定预算100，互补统计表示并集潜力，不保证合并后保留全部命中。", ""]
    return "\n".join(lines)


def _sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_jsonl(path):
    with path.open(encoding="utf-8") as source:
        return [json.loads(line) for line in source if line.strip()]


def run_experiment(data_dir, output_dir, **kwargs):
    data_dir, output_dir = Path(data_dir).resolve(), Path(output_dir).resolve()
    if data_dir == output_dir or data_dir in output_dir.parents or output_dir in data_dir.parents:
        raise ValueError("Output must be separate from input directories and their ancestors")
    manifest_path = output_dir / "experiment_manifest.json"
    if output_dir.exists() and any(output_dir.iterdir()):
        if not manifest_path.exists() or json.loads(manifest_path.read_text(encoding="utf-8")).get("experiment_id") != EXPERIMENT_ID:
            raise ValueError("Refusing to overwrite unrelated existing artifacts")
    source_paths = [data_dir / name for name in ("businesses.jsonl", "interactions.jsonl")]
    hashes_before = {path.name: _sha256(path) for path in source_paths}
    business_rows = _read_jsonl(source_paths[0])
    businesses = {row["business_id"]: row for row in business_rows}
    if len(businesses) != len(business_rows):
        raise ValueError("Duplicate business_id")
    report, artifacts = evaluate_dataset(_read_jsonl(source_paths[1]), businesses, **kwargs)
    if hashes_before != {path.name: _sha256(path) for path in source_paths}:
        raise RuntimeError("Source data changed during the experiment")
    from app.retrieval import baselines

    manifest = {
        "experiment_id": EXPERIMENT_ID, "config": report["config"],
        "inputs": {path.name: {"sha256": hashes_before[path.name], "bytes": path.stat().st_size}
                   for path in source_paths},
        "code_sha256": {Path(__file__).name: _sha256(Path(__file__)),
                        Path(baselines.__file__).name: _sha256(Path(baselines.__file__))},
        "environment": {"python": platform.python_version(), "executable": sys.executable,
                        "platform": platform.platform(), "dependencies": "Python standard library"},
        "counts": {name: len(values) for name, values in artifacts.items()},
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    for name, value in (("metrics.json", report), ("experiment_manifest.json", manifest)):
        (output_dir / name).write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    for name, values in artifacts.items():
        filename = "request_trace.jsonl" if name == "traces" else f"{name}.jsonl"
        with (output_dir / filename).open("w", encoding="utf-8") as out:
            for row in values:
                out.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
    (output_dir / "report.md").write_text(render_report(report), encoding="utf-8")
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=Path("data/processed"))
    parser.add_argument("--output-dir", type=Path, default=Path("data/derived/baseline_recall_v1"))
    parser.add_argument("--validation-cutoff")
    parser.add_argument("--test-cutoff")
    parser.add_argument("--candidate-limit", type=int, default=100)
    parser.add_argument("--radius-km", type=float, default=10.0)
    parser.add_argument("--neighbor-limit", type=int, default=50)
    parser.add_argument("--shrinkage", type=float, default=5.0)
    args = parser.parse_args(argv)
    if bool(args.validation_cutoff) != bool(args.test_cutoff):
        parser.error("Supply both time cutoffs or neither")
    report = run_experiment(args.data_dir, args.output_dir, candidate_limit=args.candidate_limit,
                            radius_km=args.radius_km, neighbor_limit=args.neighbor_limit,
                            shrinkage=args.shrinkage,
                            cutoffs=(args.validation_cutoff, args.test_cutoff) if args.validation_cutoff else None)
    print(json.dumps({"output_dir": str(args.output_dir), "cutoffs": report["config"]["cutoffs"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
