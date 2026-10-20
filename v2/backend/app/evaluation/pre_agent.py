"""Explicit, bounded DeepSeek/template comparison on curated snapshots.

Default is offline. --live consumes API quota for at most five queries with no
automatic retries. Provider credentials and response bodies are never logged.
"""
import argparse
from collections import Counter
from dataclasses import replace
import json
from pathlib import Path
import statistics
import tempfile
import time

from app import artifact_io
from app.models import RecommendationRequest, RecommendationResponse
from app.rag.generation import AnswerService
from app.rag.settings import RagSettings, load_settings
from app.evaluation.query_quality import ROOT, read_csv, score_review

EXPERIMENT_ID = 'pre_agent_comparison_v1'
DEFAULT_IDS = ['q11', 'q12', 'q13', 'q14', 'q15']


def comparison_provenance(settings):
    return {'code_sha256':{str(p.relative_to(ROOT)).replace('\\','/'):artifact_io.file_sha256(p)
                           for p in sorted((ROOT/'app').rglob('*.py'))},
            'effective_settings':{name:getattr(settings,name) for name in
                ('model','base_url','enabled','timeout_seconds','max_tokens','max_context_chars','max_restaurants')}}


def selection_summary(query_id, answer, labels):
    lookup = {(r['query_id'], r['business_id'], r['review_id'], r['excerpt']):r['stance']
              for r in labels if r['kind']=='evidence' and r['stance']}
    counts = Counter()
    for citation in answer['citations']:
        stance = lookup.get((query_id,citation['business_id'],citation['review_id'],citation['excerpt']))
        counts[stance or 'unjudged'] += 1
    judged = sum(v for k,v in counts.items() if k!='unjudged')
    return {'selected':len(answer['citations']), 'judged':judged, 'stance_counts':dict(sorted(counts.items())),
            'silver_support_fraction':counts['support']/judged if judged else None,
            'label_source':'agent_reviewed_silver_not_human_gold'}


def run_comparison(snapshot_dir, reviews, *, settings, live=False, query_ids=None, provider=None, labels=()):
    query_ids = DEFAULT_IDS if query_ids is None else query_ids
    if not 1 <= len(query_ids) <= 5 or len(set(query_ids)) != len(query_ids):
        raise ValueError('Select one to five distinct queries')
    if live and (not settings.api_key or not settings.enabled):
        raise ValueError('Live comparison requires configured enabled provider')
    snapshot_dir = Path(snapshot_dir)
    manifest = artifact_io.verify_artifacts(snapshot_dir,'experiment_manifest.json')
    if manifest['experiment_id'] != 'query_quality_v1':
        raise ValueError('Wrong query snapshot')
    cases = {t['query_id']:t for t in json.loads((snapshot_dir/'query_results.json').read_text(encoding='utf-8'))}
    if any(q not in cases for q in query_ids):
        raise ValueError('Unknown query IDs')
    offline_settings = replace(settings,api_key='')
    template_service = AnswerService(offline_settings)
    candidate_service = AnswerService(settings,provider) if live else template_service
    traces = []
    stop_reason = None
    for query_id in query_ids:
        case = cases[query_id]
        # Generation only consumes query plus frozen result facts; no user profile
        # or exact request coordinates are introduced by this replay.
        request = RecommendationRequest(query=case['query'],latitude=0,longitude=0,generate_answer=True)
        response = RecommendationResponse(version='v2',engine=case['engine'],recommendations=case['recommendations'])
        before = [(r.business_id,r.score) for r in response.recommendations]
        started = time.perf_counter()
        template = template_service.generate(request,response,reviews)
        template_seconds = time.perf_counter()-started
        started = time.perf_counter()
        candidate = candidate_service.generate(request,response,reviews)
        candidate_seconds = time.perf_counter()-started
        violations = 0
        for citation in candidate['citations']:
            owned = [r for r in reviews.get(citation['business_id'],[]) if r['review_id']==citation['review_id']]
            if not any(citation['excerpt'] in r['text'] for r in owned):
                violations += 1
        ranking_changed = before != [(r.business_id,r.score) for r in response.recommendations]
        traces.append({'query_id':query_id, 'query':case['query'], 'template':template, 'candidate':candidate,
                       'template_generation_wall_seconds':template_seconds,
                       'candidate_generation_wall_seconds':candidate_seconds,
                       'citation_violations':violations, 'ranking_changed':ranking_changed,
                       'template_selection':selection_summary(query_id,template,labels),
                       'candidate_selection':selection_summary(query_id,candidate,labels)})
        if candidate['reason'] in ('authentication_failed','rate_limited','provider_unavailable'):
            stop_reason = candidate['reason']
            break
    elapsed = [t['candidate_generation_wall_seconds'] for t in traces if t['candidate']['provider_attempted']]
    usage = Counter()
    for trace in traces:
        usage.update(trace['candidate']['usage'])
    return {'experiment_id':EXPERIMENT_ID,'scope':'bounded curated generation smoke test; not production latency or human quality',
            'snapshot_id':manifest.get('snapshot_id'), 'live_requested':live,
            'requested_queries':len(query_ids),'completed_queries':len(traces),
            'provider_attempts':sum(t['candidate']['provider_attempted'] for t in traces),
            'generated':sum(t['candidate']['mode']=='deepseek_plan' for t in traces),
            'all_live_generations_succeeded':all(t['candidate']['mode']=='deepseek_plan' for t in traces) and len(traces)==len(query_ids) if live else None,
            'citation_violations':sum(t['citation_violations'] for t in traces),
            'ranking_changes':sum(t['ranking_changed'] for t in traces),
            'stop_reason':stop_reason,'token_usage':dict(sorted(usage.items())),
            'generation_wall_seconds_median':statistics.median(elapsed) if elapsed else None,
            'generation_wall_seconds_max':max(elapsed) if elapsed else None,
            'model':settings.model if live else None,
            'query_results':[{k:v for k,v in t.items() if k not in ('template','candidate','query')} |
                             {'mode':t['candidate']['mode'],'reason':t['candidate']['reason'],'usage':t['candidate']['usage']}
                             for t in traces]},traces


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--snapshot-dir',type=Path,default=ROOT/'data/derived/query_quality_final')
    parser.add_argument('--output-dir',type=Path,default=ROOT/'data/derived/pre_agent_comparison_offline')
    parser.add_argument('--silver-labels',type=Path)
    parser.add_argument('--query-ids',nargs='+',default=DEFAULT_IDS)
    parser.add_argument('--live',action='store_true',help='Explicitly authorize up to five paid requests, no retries')
    args = parser.parse_args(argv)
    snapshot, output = args.snapshot_dir.resolve(), args.output_dir.resolve()
    if output == snapshot or output in snapshot.parents or snapshot in output.parents:
        raise ValueError('Output must be separate from source snapshot')
    if output.exists():
        previous = artifact_io.verify_artifacts(output,'experiment_manifest.json')
        if previous['experiment_id'] != EXPERIMENT_ID:
            raise ValueError('Unrelated output directory')
    labels = ()
    if args.silver_labels:
        score_review(snapshot,args.silver_labels)
        labels = read_csv(args.silver_labels)
    from app.data_repository import ProcessedDatasetRepository
    dataset = ProcessedDatasetRepository(ROOT/'data/processed')
    source_manifest=artifact_io.verify_artifacts(snapshot,'experiment_manifest.json')
    review_hash=artifact_io.file_sha256(dataset.data_dir/'representative_reviews.jsonl')
    if source_manifest['inputs']['representative_reviews.jsonl'] != review_hash:
        raise ValueError('Review dataset differs from the source snapshot')
    reviews = dataset.load_representative_reviews_by_business()
    settings = load_settings() if args.live else RagSettings()
    provenance=comparison_provenance(settings)
    report,traces = run_comparison(snapshot,reviews,settings=settings,live=args.live,query_ids=args.query_ids,labels=labels)
    output.parent.mkdir(parents=True,exist_ok=True)
    inputs = {'source_manifest':artifact_io.file_sha256(snapshot/'experiment_manifest.json'),
              'reviews':review_hash}
    if args.silver_labels:inputs['silver_labels']=artifact_io.file_sha256(args.silver_labels)
    with tempfile.TemporaryDirectory(prefix='.pre-agent-',dir=output.parent) as temporary:
        stage = Path(temporary)
        for name,value in [('metrics.json',report),('query_results.json',traces)]:
            (stage/name).write_text(json.dumps(value,ensure_ascii=False,sort_keys=True,indent=2)+'\n',encoding='utf-8')
        artifact_io.publish_directory(stage,output,{'experiment_id':EXPERIMENT_ID,'inputs':inputs,
            'runner_sha256':artifact_io.file_sha256(__file__),'live_requested':args.live,**provenance},'experiment_manifest.json')
    print(json.dumps(report,ensure_ascii=False,indent=2))
    return 0 if not report['citation_violations'] and not report['ranking_changes'] and not report['stop_reason'] and report['all_live_generations_succeeded'] is not False else 1


if __name__=='__main__':
    raise SystemExit(main())
