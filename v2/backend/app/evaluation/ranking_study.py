"""Train history-only LambdaRank; freeze validation choice before iterative test."""

import argparse
import hashlib
import json
import tempfile
from pathlib import Path

from app import artifact_io
from app.evaluation.baseline_replay import _read_jsonl
from app.evaluation.content_study import DEFAULT_CUTOFFS, GROUPS, MetricAccumulator, _reference_queries
from app.ranking import learned, fusion
from app.retrieval import baselines, content


DEFAULT_TRAIN_CUTOFF = '2016-01-01 00:00:00'
CONFIGS = {
    'city_preference': {'popularity':1, 'itemcf':.5, 'content':.1},
    'simulated_geo': {'popularity':1, 'itemcf':1, 'content':1},
}


def candidates(index, user, scenario):
    radius = None if scenario == 'city_preference' else 10.
    allowed, _, _ = index.candidate_pool(user, radius_km=radius)
    channels = {s:index.recommend(user,s,radius_km=radius) for s in ('popularity','itemcf','content')}
    result = fusion.fuse_rrf(channels, weights=CONFIGS[scenario], allowed=allowed)
    ids = [r['business_id'] for r in result]
    if len(ids)>100 or len(set(ids))!=len(ids) or not set(ids)<=allowed:
        raise AssertionError('Candidate contract violated')
    return result, allowed


def evaluate(index, queries, booster, progress):
    scenarios = {}
    for scenario in CONFIGS:
        counts = {method:{g:MetricAccumulator() for g in GROUPS} for method in ('rrf','lambdarank')}
        digest = hashlib.sha256()
        for n,target in enumerate(queries,1):
            user,item=target['user_id'],target['business_id']
            recs,allowed=candidates(index,user,scenario)
            learned_recs=learned.rank_candidates(booster,recs,index.profile(user),index.businesses,index.popularity)
            ids=[r['business_id'] for r in recs];ranked=[r['business_id'] for r in learned_recs]
            if set(ids)!=set(ranked):raise AssertionError('Ranker changed candidates')
            for method,order in [('rrf',ids),('lambdarank',ranked)]:
                counts[method]['all'].add(order,item,eligible=item in allowed)
                counts[method][target['reference_cohort']].add(order,item,eligible=item in allowed)
            digest.update(json.dumps([user,ids,ranked],separators=(',',':')).encode())
            if progress and n%10000==0:print(f'{scenario}: {n}/{len(queries)}',flush=True)
        scenarios[scenario]={'engines':{m:{g:a.result(catalog_size=len(index.visible_business_ids)) for g,a in groups.items()} for m,groups in counts.items()},
                             'candidate_and_order_sha256':digest.hexdigest(),'constraint_violations':0}
    return scenarios


def run_ranking_study(data_dir, output_dir, *, cutoffs=(DEFAULT_TRAIN_CUTOFF,*DEFAULT_CUTOFFS), progress=True):
    import lightgbm as lgb
    import numpy as np
    data_dir,output_dir=Path(data_dir).resolve(),Path(output_dir).resolve()
    if data_dir==output_dir or data_dir in output_dir.parents or output_dir in data_dir.parents:
        raise ValueError('Ranking output must be separate from data')
    if output_dir.exists() and any(output_dir.iterdir()):
        manifest=output_dir/'experiment_manifest.json'
        if not manifest.exists() or json.loads(manifest.read_text())['experiment_id']!=learned.VERSION:raise ValueError('Unrelated output')
    if (data_dir/'data_manifest.json').exists():artifact_io.verify_artifacts(data_dir,'data_manifest.json')
    inputs={n:artifact_io.file_sha256(data_dir/n) for n in ('businesses.jsonl','interactions.jsonl')}
    business_rows=_read_jsonl(data_dir/'businesses.jsonl');businesses={b['business_id']:b for b in business_rows}
    if len(business_rows)!=len(businesses):raise ValueError('Duplicate business IDs')
    rows=baselines.validate_interactions(_read_jsonl(data_dir/'interactions.jsonl'),businesses)
    train_cut,val_cut,test_cut=[baselines.parse_time(t).isoformat(sep=' ') for t in cutoffs]
    if not rows or not rows[0]['event_time']<train_cut<val_cut<test_cut<=rows[-1]['event_time']:raise ValueError('Invalid windows')
    if progress:print('Building frozen train features',flush=True)
    index=content.build_content_index(rows,businesses,train_cut)
    queries,train_reference=_reference_queries(rows,train_cut,val_cut)
    x,y,groups=[],[],[]
    for n,target in enumerate(queries,1):
        # One city ranking task, with all candidates exactly as retrieved; no
        # injection of the known future positive into a missed candidate list.
        recs,_=candidates(index,target['user_id'],'city_preference')
        if len(recs)>=2 and any(r['business_id']==target['business_id'] for r in recs):
            profile=index.profile(target['user_id'])
            x.extend(learned.feature_row(r,profile,businesses[r['business_id']],index.popularity.get(r['business_id'],{})) for r in recs)
            y.extend(int(r['business_id']==target['business_id']) for r in recs)
            groups.append(len(recs))
        if progress and n%10000==0:print(f'train: {n}/{len(queries)}',flush=True)
    if not groups:raise ValueError('No positive candidate groups for learning to rank')
    params={'objective':'lambdarank','metric':'ndcg','verbosity':-1,'seed':2026,
            'num_threads':1,'deterministic':True,'force_col_wise':True,'num_leaves':15,
            'learning_rate':.05,'min_data_in_leaf':20,'feature_pre_filter':False}
    booster=lgb.train(params,lgb.Dataset(np.asarray(x,dtype=np.float64),label=y,group=groups,feature_name=learned.FEATURES),num_boost_round=40)
    training={'requests':len(queries),'positive_groups':len(groups),'candidate_rows':len(y),'injected_targets':0,
              'feature_cutoff':train_cut,'label_end_exclusive':val_cut,
              'label_policy':'first future unseen high-rating target; other retrieved candidates are unlabeled proxy negatives, not dislikes',
              'reference':train_reference}
    del x,y,index
    if progress:print('Validation; selection will freeze before test',flush=True)
    index=content.build_content_index(rows,businesses,val_cut)
    val_queries,val_reference=_reference_queries(rows,val_cut,test_cut)
    validation=evaluate(index,val_queries,booster,progress)
    selection={scenario:learned.choose_order({m:g['all'] for m,g in result['engines'].items()}) for scenario,result in validation.items()}
    selection_digest=hashlib.sha256(json.dumps(selection,sort_keys=True).encode()).hexdigest()
    output_dir.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.ranking-',dir=output_dir.parent) as temporary:
        stage=Path(temporary)
        (stage/'selection.json').write_text(json.dumps(selection,sort_keys=True,indent=2)+'\n',encoding='utf-8')
        if progress:print('Selection frozen: '+json.dumps(selection)+'; iterative test',flush=True)
        del index
        index=content.build_content_index(rows,businesses,test_cut)
        test_queries,test_reference=_reference_queries(rows,test_cut,None)
        test=evaluate(index,test_queries,booster,progress)
        if hashlib.sha256(json.dumps(selection,sort_keys=True).encode()).hexdigest()!=selection_digest:raise AssertionError('Selection changed')
        report={'experiment_id':learned.VERSION,'test_is_iterative':True,'training':training,'validation':validation,'test':test,
                'selection':selection,'selection_policy':'validation NDCG@10; ties retain RRF; one fixed model, no test tuning',
                'target_references':{'validation':val_reference,'test':test_reference},
                'candidate_policy':CONFIGS,'feature_schema':learned.FEATURES,
                'query_reranking_supported':False,'parameters':params,'num_boost_round':40}
        booster.save_model(str(stage/'model.txt'))
        (stage/'metrics.json').write_text(json.dumps(report,sort_keys=True,indent=2)+'\n',encoding='utf-8')
        for name,digest in inputs.items():
            if artifact_io.file_sha256(data_dir/name)!=digest:raise RuntimeError('Inputs changed')
        manifest={'experiment_id':learned.VERSION,'feature_schema':learned.FEATURES,'selection_sha256':selection_digest,
                  'candidate_policy':CONFIGS,
                  'catalog_ids':sorted(businesses),'inputs':inputs,'training_cutoff':train_cut,'validation_cutoff':val_cut,
                  'test_cutoff':test_cut,'library_versions':{'numpy':np.__version__,'lightgbm':lgb.__version__},
                  'code_sha256':{m.__name__:artifact_io.file_sha256(m.__file__) for m in (learned,content,baselines,fusion,artifact_io)},
                  'runner_sha256':artifact_io.file_sha256(__file__)}
        artifact_io.publish_directory(stage,output_dir,manifest,'experiment_manifest.json')
    return report


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data-dir',type=Path,default=Path('data/derived/tampa_full_reviews_v1'))
    parser.add_argument('--output-dir',type=Path,default=Path('data/derived/ranking_v1'))
    args=parser.parse_args(argv)
    report=run_ranking_study(args.data_dir,args.output_dir)
    print(json.dumps({'selection':report['selection'],'training':report['training']},indent=2))
    return 0


if __name__=='__main__':raise SystemExit(main())
