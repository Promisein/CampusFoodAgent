import copy
import json


def fixture():
    businesses = {item: {"business_id": item, "categories_normalized": [category],
                         "latitude": 0, "longitude": 0, "price_level": 1}
                  for item, category in [("A", "Coffee"), ("B", "Coffee"), ("C", "Pizza")]}
    entries = [("u", "A", "2020-01-01"), ("v", "A", "2020-01-01"),
               ("v", "B", "2020-01-02"), ("w", "C", "2020-01-02"),
               ("u", "B", "2020-02-02"), ("new", "C", "2020-02-03"),
               ("u", "C", "2020-03-02"), ("later", "B", "2020-03-03")]
    rows = [{"interaction_id": str(i), "user_id": user, "business_id": item,
             "rating": 5, "event_time": time} for i, (user, item, time) in enumerate(entries)]
    return rows, businesses


CUTOFFS = ("2020-02-01", "2020-03-01")


def test_configuration_selection_is_validation_only_and_frozen_before_test():
    from app.evaluation.fusion_study import evaluate_fusion

    rows, businesses = fixture()
    frozen = []
    report1, _ = evaluate_fusion(rows, businesses, cutoffs=CUTOFFS, freeze_callback=lambda selection: frozen.append(copy.deepcopy(selection)))
    changed = copy.deepcopy(rows)
    changed[-1]["rating"] = 1
    report2, _ = evaluate_fusion(changed, businesses, cutoffs=CUTOFFS)
    assert report1["selection"] == report2["selection"] == frozen[0]
    assert report1["validation"] == report2["validation"]
    assert report1["test_is_iterative"] is True
    for scenario, values in report1["test"]["scenarios"].items():
        assert set(values["engines"]) == {"popularity", "dual_alternate", report1["selection"][scenario]["name"]}
        assert values["constraint_violations"] == 0


def test_selection_uses_ndcg_then_recall_and_stable_name_ties():
    from app.evaluation.fusion_study import choose_config

    configs = {name: {"name": name, "mode": "rrf"} for name in ("A", "B", "C")}
    metrics = {"A": {"all": {"ndcg@10": .2, "recall@20": .4, "recall@100": .5}},
               "B": {"all": {"ndcg@10": .3, "recall@20": .1, "recall@100": .4}},
               "C": {"all": {"ndcg@10": .3, "recall@20": .1, "recall@100": .4}}}
    assert choose_config(metrics, configs)["name"] == "B"


def test_fusion_study_cli_writes_frozen_selection_and_reproduces(tmp_path):
    from app.evaluation.fusion_study import main

    rows, businesses = fixture()
    source, out = tmp_path / "full", tmp_path / "fusion"
    source.mkdir()
    for name, records in (("businesses.jsonl", businesses.values()), ("interactions.jsonl", rows)):
        (source / name).write_text("".join(json.dumps(row)+"\n" for row in records), encoding="utf-8")
    args = ["--data-dir", str(source), "--output-dir", str(out), "--validation-cutoff", CUTOFFS[0], "--test-cutoff", CUTOFFS[1]]
    assert main(args) == 0
    assert (out / "selection.json").exists()
    first = {path.name: path.read_bytes() for path in out.iterdir()}
    assert main(args) == 0
    assert first == {path.name: path.read_bytes() for path in out.iterdir()}
