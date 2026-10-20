"""Offline real-catalog contract audit and an explicitly unjudged review pool.

No settings file, HTTP provider, live event store or human labels are read by
the audit. Human relevance and stance are imported separately with provenance.
"""
import argparse
from collections import Counter, defaultdict
import csv
import hashlib
import json
import math
from pathlib import Path
import tempfile

from app import artifact_io
from app.data_repository import ProcessedDatasetRepository
from app.evidence import link_answer_evidence
from app.models import RecommendationRequest
from app.personalized import recommend_anonymous, recommend_personalized
from app.rag.generation import AnswerService
from app.rag.settings import RagSettings
from app.recommender import _haversine_km

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CASES = ROOT/'data/fixtures/query_quality_v1.json'
EXPERIMENT_ID = 'query_quality_v1'
LABEL_FIELDS = {'relevance', 'stance', 'reviewer', 'note'}
FIELDS = ['snapshot_id', 'record_id', 'kind', 'query_id', 'query', 'business_id',
          'name', 'rank', 'categories', 'review_id', 'excerpt', 'cue',
          'citation_id', 'used_in_answer', 'relevance', 'stance', 'reviewer', 'note']
STANCES = {'support', 'contradict', 'mention_only', 'irrelevant', 'unclear'}


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def spreadsheet_text(value):
    value = str(value)
    return "'" + value if value.lstrip().startswith(('=', '+', '-', '@')) else value


def write_csv(path, rows):
    with path.open('w', encoding='utf-8-sig', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)


def read_csv(path):
    with Path(path).open(encoding='utf-8-sig', newline='') as stream:
        reader = csv.DictReader(stream)
        if reader.fieldnames != FIELDS:
            raise ValueError('Review sheet columns changed')
        return list(reader)


def score_rows(expected, submitted):
    """Accept only labels attached to unchanged snapshot rows; never infer labels."""
    by_id = {r['record_id']: r for r in expected}
    if len(by_id) != len(expected):
        raise ValueError('Duplicate snapshot rows')
    seen = set()
    grades = {}
    stances = Counter()
    for row in submitted:
        record_id = row.get('record_id')
        if record_id not in by_id or record_id in seen:
            raise ValueError('Unknown or duplicate review row')
        seen.add(record_id)
        original = by_id[record_id]
        if set(row) != set(original) or any(row[k] != v for k, v in original.items() if k not in LABEL_FIELDS):
            raise ValueError('Stale or edited snapshot content')
        relevance, stance = row.get('relevance', ''), row.get('stance', '')
        if not relevance and not stance:
            continue
        if not row.get('reviewer', '').strip():
            raise ValueError('Labeled rows require reviewer attribution')
        if row['kind'] == 'restaurant' and relevance in ('0', '1', '2', '3') and not stance:
            grades[record_id] = int(relevance)
        elif row['kind'] == 'evidence' and stance in STANCES and not relevance:
            stances[stance] += 1
        else:
            raise ValueError('Invalid relevance or stance label')
    groups = defaultdict(list)
    for row in expected:
        if row['kind'] == 'restaurant':
            groups[row['query_id']].append(row)
    precision, ndcg = [], []
    for rows in groups.values():
        if not all(r['record_id'] in grades for r in rows):
            continue
        ordered = sorted(rows, key=lambda r: int(r['rank']))
        values = [grades[r['record_id']] for r in ordered]
        # Precision over returned results (at most five); no invented missing grades.
        precision.append(sum(g >= 2 for g in values[:5])/len(values[:5]))
        dcg = lambda scores: sum((2**g-1)/math.log2(i+2) for i, g in enumerate(scores[:5]))
        ideal = dcg(sorted(values, reverse=True))
        ndcg.append(dcg(values)/ideal if ideal else 0.)
    total_restaurants = sum(r['kind'] == 'restaurant' for r in expected)
    total_evidence = sum(r['kind'] == 'evidence' for r in expected)
    return {'label_source': 'reviewer_supplied_labels_not_independently_verified',
            'restaurant_total': total_restaurants, 'restaurant_judged': len(grades),
            'evidence_total': total_evidence, 'evidence_judged': sum(stances.values()),
            'complete_relevance_queries': len(precision),
            'restaurant_coverage': len(grades)/total_restaurants if total_restaurants else None,
            'evidence_coverage': sum(stances.values())/total_evidence if total_evidence else None,
            'precision_at_5_complete_queries': sum(precision)/len(precision) if precision else None,
            'pooled_ndcg_at_5_complete_queries': sum(ndcg)/len(ndcg) if ndcg else None,
            'evidence_stance_counts': dict(sorted(stances.items())),
            'limitations': 'complete returned pools only; no catalog-wide recall, blind test or inferred human labels'}


def score_review(directory, labels_path):
    directory = Path(directory)
    manifest = artifact_io.verify_artifacts(directory, 'experiment_manifest.json')
    if manifest['experiment_id'] != EXPERIMENT_ID:
        raise ValueError('Wrong review snapshot')
    return score_rows(read_csv(directory/'review_sheet.csv'), read_csv(labels_path))


def contract_errors(case, request, response, businesses):
    """Check authored expectations against raw catalog; not parser self-agreement."""
    expected = case['expected']
    errors = []
    recs = response.recommendations
    clarified = response.engine == 'query_needs_clarification'
    outcome = 'clarify' if clarified else 'results' if recs else 'empty'
    if outcome != expected['outcome']:
        errors.append('unexpected_outcome')
    if len(recs) > request.top_k or len({r.business_id for r in recs}) != len(recs):
        errors.append('top_k_or_duplicate')
    for rec in recs:
        business = businesses[rec.business_id]
        categories = {c.casefold() for c in business['categories_normalized']}
        if expected.get('include_any') and not categories.intersection(c.casefold() for c in expected['include_any']):
            errors.append('category_include')
        if categories.intersection(c.casefold() for c in expected.get('exclude_any', [])):
            errors.append('category_exclude')
        radius = min(request.radius_km, expected.get('radius_km', request.radius_km))
        distance = _haversine_km(request.latitude, request.longitude, business['latitude'], business['longitude'])
        if distance > radius + 1e-9:
            errors.append('radius')
        if business['price_level'] > min(request.max_price_level, expected.get('max_price_level', request.max_price_level)):
            errors.append('price')
        if business['city'].casefold() != request.city.casefold() or not business['is_open']:
            errors.append('city_or_snapshot_open')
    return sorted(set(errors))


def run_study(cases_path, output_dir, *, dataset, serving=None, search=None, ranker=None, defaults=None):
    cases_path, output_dir = Path(cases_path).resolve(), Path(output_dir).resolve()
    if output_dir == cases_path.parent or output_dir in cases_path.parents or cases_path.parent in output_dir.parents:
        raise ValueError('Output overlaps fixture directory')
    if output_dir.exists():
        manifest = artifact_io.verify_artifacts(output_dir, 'experiment_manifest.json')
        if manifest['experiment_id'] != EXPERIMENT_ID:
            raise ValueError('Unrelated output directory')
    fixture = json.loads(cases_path.read_text(encoding='utf-8'))
    ids = [case['id'] for case in fixture['cases']]
    if not ids or len(ids) != len(set(ids)):
        raise ValueError('Duplicate or empty query cases')
    inputs = {'cases': artifact_io.file_sha256(cases_path)}
    for name in ('businesses.jsonl', 'representative_reviews.jsonl', 'data_manifest.json'):
        inputs[name] = artifact_io.file_sha256(dataset.data_dir/name)
    for name, repository in [('history', serving), ('search', search), ('ranker', ranker)]:
        if repository is not None:
            repository.load()  # validate dependencies before auditing; fail instead of silently omitting them
            # The manifest of each loaded bundle is also bound below, independent of path naming.
            inputs[name] = digest(repository.load()['manifest'])
    code = {str(p.relative_to(ROOT)).replace('\\', '/'): artifact_io.file_sha256(p)
            for p in sorted((ROOT/'app').rglob('*.py'))}
    configuration = {'latitude':27.9506, 'longitude':-82.4572, 'radius_km':5,
                     'max_price_level':4, 'top_k':5, **(defaults or {})}
    snapshot_id = digest({'inputs':inputs, 'code':code, 'defaults':configuration})
    reviews = dataset.load_representative_reviews_by_business()
    businesses = {b['business_id']: b for b in dataset.load_businesses()}
    service = AnswerService(RagSettings(api_key=''))
    traces, sheet = [], []
    for case in fixture['cases']:
        request = RecommendationRequest(**{**configuration, **case['request'], 'generate_answer':True})
        if request.user_id:
            if serving is None:
                raise ValueError('Personalized case requires history repository')
            response = recommend_personalized(request, dataset, serving, search_repository=search, ranking_repository=ranker)
        else:
            response = recommend_anonymous(request, dataset, search_repository=search)
        response.answer = service.generate(request, response, reviews)
        link_answer_evidence(response)
        errors = contract_errors(case, request, response, businesses)
        citation_violations = mismatches = 0
        by_id = {r.business_id: r for r in response.recommendations}
        for citation in response.answer['citations']:
            owned = [r for r in reviews.get(citation['business_id'], []) if r['review_id'] == citation['review_id']]
            if not any(citation['excerpt'] in r['text'] for r in owned):
                citation_violations += 1
            rec = by_id.get(citation['business_id'])
            if rec is None or not any(e.document_id == citation['review_id'] and e.excerpt == citation['excerpt']
                                     and e.citation_id == citation['id'] and e.used_in_answer for e in rec.evidence):
                mismatches += 1
        for rank, rec in enumerate(response.recommendations, 1):
            base = {key:'' for key in FIELDS}
            base.update(snapshot_id=snapshot_id, query_id=case['id'], query=request.query,
                        business_id=rec.business_id, name=rec.name, rank=str(rank),
                        categories=' | '.join(rec.categories))
            restaurant = {**base, 'record_id':digest([snapshot_id, case['id'], rec.business_id, 'restaurant']), 'kind':'restaurant'}
            sheet.append({k:spreadsheet_text(v) for k, v in restaurant.items()})
            for evidence in rec.evidence:
                quote = {**base, 'record_id':digest([snapshot_id, case['id'], rec.business_id, evidence.document_id]),
                         'kind':'evidence', 'review_id':evidence.document_id, 'excerpt':evidence.excerpt or '',
                         'cue':evidence.cue, 'citation_id':evidence.citation_id or '',
                         'used_in_answer':str(evidence.used_in_answer).lower()}
                sheet.append({k:spreadsheet_text(v) for k, v in quote.items()})
        traces.append({'query_id':case['id'], 'group':case['group'], 'query':request.query,
                       'expected':case['expected'], 'errors':errors, 'engine':response.engine,
                       'recommendations':[r.model_dump() for r in response.recommendations],
                       'answer':response.answer, 'citation_violations':citation_violations,
                       'card_answer_mismatches':mismatches, 'warnings':response.metadata.get('warnings', [])})
    report = {'experiment_id':EXPERIMENT_ID, 'snapshot_id':snapshot_id,
              'label_source':fixture['label_source'], 'requests':len(traces),
              'contract_passed':sum(not t['errors'] for t in traces),
              'contract_failures':{t['query_id']:t['errors'] for t in traces if t['errors']},
              'citation_violations':sum(t['citation_violations'] for t in traces),
              'card_answer_mismatches':sum(t['card_answer_mismatches'] for t in traces),
              'live_provider_calls':sum(t['answer']['provider_attempted'] for t in traces),
              'recommendations':sum(len(t['recommendations']) for t in traces),
              'answer_citations':sum(len(t['answer']['citations']) for t in traces),
              'empty_or_clarification':sum(not t['recommendations'] for t in traces),
              'recommendations_without_related_evidence':sum(r['evidence_status']=='insufficient' for t in traces for r in t['recommendations']),
              'review_status':score_rows(sheet, sheet),
              'scope':'curated real-catalog functional audit; not human gold, model quality or blind evaluation'}
    if inputs['cases'] != artifact_io.file_sha256(cases_path):
        raise RuntimeError('Cases changed during audit')
    for name in ('businesses.jsonl','representative_reviews.jsonl','data_manifest.json'):
        if inputs[name] != artifact_io.file_sha256(dataset.data_dir/name):
            raise RuntimeError('Dataset changed during audit')
    output_dir.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.query-quality-', dir=output_dir.parent) as temporary:
        stage = Path(temporary)
        for name, value in [('metrics.json', report), ('query_results.json', traces)]:
            (stage/name).write_text(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2)+'\n', encoding='utf-8')
        write_csv(stage/'review_sheet.csv', sheet)
        artifact_io.publish_directory(stage, output_dir,
            {'experiment_id':EXPERIMENT_ID, 'inputs':inputs, 'code_sha256':code, 'snapshot_id':snapshot_id},
            'experiment_manifest.json')
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cases', type=Path, default=DEFAULT_CASES)
    parser.add_argument('--output-dir', type=Path, default=ROOT/'data/derived/query_quality_v1')
    parser.add_argument('--labels', type=Path, help='Score a separate completed sheet against the immutable audit')
    args = parser.parse_args(argv)
    if args.labels:
        result = score_review(args.output_dir, args.labels)
    else:
        from app.retrieval.semantic import SearchRepository
        from app.serving.model import ServingRepository
        from app.ranking.learned import RankingRepository
        result = run_study(args.cases, args.output_dir, dataset=ProcessedDatasetRepository(ROOT/'data/processed'),
                           serving=ServingRepository(ROOT/'data/derived/serving_v1'),
                           search=SearchRepository(ROOT/'data/derived/search_v1'),
                           ranker=RankingRepository(ROOT/'data/derived/ranking_v1'))
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if args.labels or result['contract_passed'] == result['requests'] and not result['citation_violations'] and not result['card_answer_mismatches'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
