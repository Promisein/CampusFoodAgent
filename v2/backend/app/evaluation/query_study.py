"""Reproducible, hand-labeled query regression study, not a Yelp relevance test."""

import argparse
import json
import math
import tempfile
from pathlib import Path

from app import artifact_io, evidence, personalized, query_intent, recommender, models
from app.data_repository import ProcessedDatasetRepository
from app.models import RecommendationRequest
from app.retrieval import baselines, content, query
from app.ranking import fusion
from app.serving import model


DEFAULT_CASES = Path(__file__).resolve().parents[2] / 'data/fixtures/query_cases_v1.json'
EXPERIMENT_ID = 'query_v1'


def fixture_service(fixture, directory):
    directory.mkdir(parents=True)
    businesses = [{
        'business_id': b['id'], 'name': b['id'], 'categories_raw': b['category'],
        'categories_normalized': [b['category']], 'city': 'Tampa', 'state': 'FL',
        'latitude': b['latitude'], 'longitude': 0, 'price_level': b['price'],
        'is_open': b.get('is_open', True), 'stars': 4, 'review_count': 10,
        'attributes': {}, 'hours': {}, 'data_version': 'query_fixture_v1',
    } for b in fixture['businesses']]
    # Fixed historical preference: u likes seed coffee. Other public synthetic users
    # connect coffee merchants, ensuring the old system has a real history signal.
    entries = [('u', 'seed'), ('x', 'seed'), ('x', 'c1'), ('y', 'seed'), ('y', 'c2')]
    entries += [('catalog', b['business_id']) for b in businesses]
    rows = [{'interaction_id': str(i), 'user_id': u, 'business_id': b,
             'rating': 5, 'event_time': '2020-01-01'} for i, (u, b) in enumerate(entries)]
    reviews = [{'review_id': r['id'], 'business_id': r['business'], 'text': r['text'],
                'user_id': 'reviewer', 'rating': 4, 'review_date': '2020-01-01', 'useful': 0,
                'source': 'synthetic_query_fixture'} for r in fixture['reviews']]
    for name, values in [('businesses.jsonl', businesses), ('interactions.jsonl', rows), ('representative_reviews.jsonl', reviews)]:
        (directory/name).write_text(''.join(json.dumps(v, sort_keys=True)+'\n' for v in values), encoding='utf-8')
    manifest={'data_version':'query_fixture_v1','outputs':{
        p.name:{'sha256':artifact_io.file_sha256(p),'bytes':p.stat().st_size} for p in sorted(directory.glob('*.jsonl'))}}
    (directory/'data_manifest.json').write_text(json.dumps(manifest,sort_keys=True),encoding='utf-8')
    config = {'name': 'rrf_triple', 'mode': 'rrf', 'k': 60,
              'weights': dict.fromkeys(model.CHANNELS, 1), 'budgets': dict.fromkeys(model.CHANNELS, 100)}
    model_dir = directory.parent/'model'
    model.build_serving_snapshot(directory, dict.fromkeys(('city_preference', 'simulated_geo'), config), model_dir)
    return ProcessedDatasetRepository(directory), model.ServingRepository(model_dir)


def historical_response(request, dataset, serving):
    """Original personalized behavior: no query filtering/channel/evidence retrieval."""
    bundle = serving.load()
    businesses = {b['business_id']: b for b in dataset.load_businesses()}
    index = model.RequestRecallIndex(bundle, businesses, request)
    channels = {s: index.recommend(request.user_id, s) for s in model.CHANNELS}
    if not index.profile(request.user_id)['positive_business_ids']:
        channels = {'popularity': channels['popularity']}
    recs = fusion.fuse_rrf(channels)[:request.top_k]
    reviews = dataset.load_representative_reviews_by_business()
    return [{'business_id': r['business_id'], 'evidence': [{'document_id': row['review_id']}
             for row in reviews.get(r['business_id'], [])[:2]]} for r in recs]


def run_study(cases_path, output_dir, *, include_search=False):
    cases_path, output_dir = Path(cases_path).resolve(), Path(output_dir).resolve()
    if output_dir == cases_path.parent or output_dir in cases_path.parents or cases_path.parent in output_dir.parents:
        raise ValueError('Output must be separate from fixture inputs')
    if output_dir.exists() and any(output_dir.iterdir()):
        manifest = output_dir/'experiment_manifest.json'
        if not manifest.exists() or json.loads(manifest.read_text())['experiment_id'] != EXPERIMENT_ID:
            raise ValueError('Unrelated output directory')
    input_hash = artifact_io.file_sha256(cases_path)
    fixture = json.loads(cases_path.read_text(encoding='utf-8'))
    traces, splits = [], {}
    with tempfile.TemporaryDirectory() as temporary:
        dataset, serving = fixture_service(fixture, Path(temporary)/'data')
        search_repository=None
        if include_search:
            from app.retrieval.semantic import build_search_index,SearchRepository
            search_dir=Path(temporary)/'search'
            build_search_index(dataset.data_dir,search_dir,dimensions=4)
            search_repository=SearchRepository(search_dir)
        for split in ('dev', 'acceptance'):
            cases = [c for c in fixture['cases'] if c['split'] == split]
            if not cases or len({c['id'] for c in fixture['cases']}) != len(fixture['cases']):
                raise ValueError('Missing split or duplicate case IDs')
            splits[split] = {}
            for engine in (('historical_only', 'query_v1', 'hybrid_search') if include_search else ('historical_only','query_v1')):
                totals = dict(constraint_violations=0, parser_exact=0, relevance_requests=0,
                              ndcg=0., recall=0., no_result_requests=0, correct_abstentions=0,
                              evidence_returned=0, evidence_correct=0, evidence_expected=0, evidence_found=0)
                for case in cases:
                    request = RecommendationRequest(**{
                        'query': case['query'], 'user_id': 'u', 'latitude': 0, 'longitude': 0,
                        'radius_km': 10, 'top_k': 5, **case.get('request', {})})
                    if engine != 'historical_only':
                        response = personalized.recommend_personalized(request, dataset, serving,
                            search_repository=search_repository if engine=='hybrid_search' else None).model_dump()
                        recs = response['recommendations']
                        actual = response['metadata']['intent']
                        expected = {'include_categories': [], 'exclude_categories': [], 'soft_topics': [],
                                    'radius_km': None, 'max_price_level': None, 'needs_clarification': False, **case['intent']}
                        totals['parser_exact'] += all(actual[k] == v for k, v in expected.items())
                    else:
                        recs = historical_response(request, dataset, serving)
                    ids = [r['business_id'] for r in recs]
                    assert len(ids) == len(set(ids))
                    totals['constraint_violations'] += len(set(ids)-set(case['allowed']))
                    relevant = set(case['relevant'])
                    if relevant:
                        totals['relevance_requests'] += 1
                        totals['recall'] += len(set(ids) & relevant)/len(relevant)
                        dcg = sum(1/math.log2(rank+2) for rank, item in enumerate(ids) if item in relevant)
                        totals['ndcg'] += dcg/sum(1/math.log2(rank+2) for rank in range(min(5, len(relevant))))
                    else:
                        totals['no_result_requests'] += 1
                        totals['correct_abstentions'] += not ids
                    if 'evidence' in case:
                        expected_docs = {d for docs in case['evidence'].values() for d in docs}
                        found = set()
                        for rec in recs:
                            docs = {d['document_id'] for d in rec['evidence']}
                            correct = docs & set(case['evidence'].get(rec['business_id'], []))
                            totals['evidence_returned'] += len(docs)
                            totals['evidence_correct'] += len(correct)
                            found.update(correct)
                        totals['evidence_expected'] += len(expected_docs)
                        totals['evidence_found'] += len(found)
                    traces.append({'case_id': case['id'], 'split': split, 'engine': engine, 'ids': ids,
                                   'evidence': {r['business_id']: [e['document_id'] for e in r['evidence']] for r in recs}})
                def ratio(n, d):
                    return n/d if d else None
                splits[split][engine] = {**totals, 'requests': len(cases),
                    'parser_exact_rate': ratio(totals['parser_exact'], len(cases)) if engine != 'historical_only' else None,
                    'ndcg@5': ratio(totals['ndcg'], totals['relevance_requests']),
                    'recall@5': ratio(totals['recall'], totals['relevance_requests']),
                    'abstention_accuracy': ratio(totals['correct_abstentions'], totals['no_result_requests']),
                    'evidence_precision': ratio(totals['evidence_correct'], totals['evidence_returned']),
                    'evidence_recall': ratio(totals['evidence_found'], totals['evidence_expected'])}
    report = {'experiment_id': EXPERIMENT_ID, 'splits': splits,
              'policy': 'fixed query weight2/k60/budget100; no parameter search on acceptance',
              'scope': fixture['scope'], 'relevance_semantics': 'soft-topic lexical relevance including negative mentions; not preference satisfaction'}
    if artifact_io.file_sha256(cases_path) != input_hash:
        raise RuntimeError('Fixture changed during study')
    output_dir.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.query-', dir=output_dir.parent) as temporary:
        stage = Path(temporary)
        (stage/'metrics.json').write_text(json.dumps(report, sort_keys=True, indent=2)+'\n', encoding='utf-8')
        (stage/'cases_results.json').write_text(json.dumps(traces, sort_keys=True, indent=2)+'\n', encoding='utf-8')
        modules = [query_intent, evidence, query, personalized, recommender, model, models, baselines, content, fusion, artifact_io]
        if include_search:
            from app.retrieval import semantic
            modules.append(semantic)
        manifest = {'experiment_id': EXPERIMENT_ID, 'fixture_sha256': input_hash,
                    'code_sha256': {m.__name__: artifact_io.file_sha256(m.__file__) for m in modules},
                    'runner_sha256': artifact_io.file_sha256(__file__)}
        artifact_io.publish_directory(stage, output_dir, manifest, 'experiment_manifest.json')
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cases', type=Path, default=DEFAULT_CASES)
    parser.add_argument('--output-dir', type=Path, default=Path('data/derived/query_v1'))
    parser.add_argument('--include-search',action='store_true',help='Evaluate BM25+LSA against the same labeled queries')
    args = parser.parse_args(argv)
    print(json.dumps(run_study(args.cases, args.output_dir,include_search=args.include_search), indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
