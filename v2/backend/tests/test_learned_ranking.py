import json

import pytest


def test_features_use_history_and_stable_schema_only():
    from app.ranking.learned import feature_row, FEATURES
    rec = {'business_id': 'b', 'score': .02, 'channel_scores': {'itemcf': {'rank': 2, 'raw_score': .4}}}
    profile = {'history_count': 5, 'positive_business_ids': ['a'], 'category_preferences': {'Pizza': 2}, 'mean_price_level': 1}
    business = {'categories_normalized': ['Pizza'], 'price_level': 2, 'stars': 5, 'review_count': 99999}
    popularity = {'score': 1, 'positive_users': 3, 'bayesian_rating': 4}
    first = feature_row(rec, profile, business, popularity)
    assert len(first) == len(FEATURES)
    assert first == feature_row(rec, profile, {**business, 'stars': 1, 'review_count': 1}, popularity)
    assert all(isinstance(v, (int, float)) for v in first)


def test_ranker_grouping_freeze_export_and_replay(tmp_path):
    from app.evaluation.ranking_study import run_ranking_study
    from app.ranking.learned import RankingRepository
    source = tmp_path/'source';source.mkdir()
    businesses = [{'business_id': i, 'name': i, 'categories_normalized': ['Pizza'], 'price_level': 1,
                   'latitude': 0, 'longitude': 0, 'city': 'Tampa', 'is_open': True} for i in 'ABCDE']
    events = [('u', 'A', '2014-01-01'), ('peer', 'A', '2014-01-01'), ('peer', 'B', '2014-01-01')]
    events += [('catalog', i, '2014-01-01') for i in 'ABCDE']
    events += [('u', 'B', '2016-06-01'), ('u', 'C', '2018-06-01'), ('u', 'D', '2020-06-01')]
    rows = [{'interaction_id': str(n), 'user_id': u, 'business_id': b, 'rating': 5, 'event_time': t} for n,(u,b,t) in enumerate(events)]
    for name,values in [('businesses.jsonl',businesses),('interactions.jsonl',rows)]:
        (source/name).write_text(''.join(json.dumps(r)+'\n' for r in values))
    out = tmp_path/'ranker'
    report = run_ranking_study(source, out, cutoffs=('2016-01-01','2017-01-01','2019-01-01'), progress=False)
    assert report['training']['positive_groups'] > 0
    assert report['training']['injected_targets'] == 0
    assert report['test_is_iterative']
    before={p.name:p.read_bytes() for p in out.iterdir()}
    assert run_ranking_study(source,out,cutoffs=('2016-01-01','2017-01-01','2019-01-01'),progress=False)==report
    assert before=={p.name:p.read_bytes() for p in out.iterdir()}
    repo = RankingRepository(out)
    bundle = repo.load()
    assert bundle['manifest']['feature_schema']
    candidates=[{'business_id':'B','score':.1,'channel_scores':{}}, {'business_id':'C','score':.05,'channel_scores':{}}]
    profile={'history_count':0,'positive_business_ids':[],'category_preferences':{},'mean_price_level':None}
    ordered,meta=repo.rerank(candidates,profile,{b['business_id']:b for b in businesses},{},query_active=True)
    assert ordered==candidates and meta['reason']=='query_task_not_trained'
    (out/'model.txt').write_text('corrupt')
    with pytest.raises(ValueError):RankingRepository(out).load()


def test_promotion_uses_validation_and_ties_keep_rrf():
    from app.ranking.learned import choose_order
    assert choose_order({'rrf':{'ndcg@10':.1},'lambdarank':{'ndcg@10':.1}})=='rrf'
    assert choose_order({'rrf':{'ndcg@10':.1},'lambdarank':{'ndcg@10':.11}})=='lambdarank'


def test_native_prediction_failure_is_recoverable():
    from app.ranking.learned import rank_candidates
    from lightgbm.basic import LightGBMError
    class Broken:
        def predict(self,*args,**kwargs):raise LightGBMError('injected native error')
    with pytest.raises(ValueError):
        rank_candidates(Broken(),[{'business_id':'b','score':.1,'channel_scores':{}}],
            {'history_count':0,'positive_business_ids':[]},{'b':{}},{})
