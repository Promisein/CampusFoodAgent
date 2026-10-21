"""Offline fixed multi-turn contracts, with isolated synthetic data and SQLite."""
import argparse
import json
from pathlib import Path
import tempfile

from app import artifact_io
from app.agent.service import AgentService
from app.agent.store import SessionRepository
from app.events import EventRepository
from app.evaluation.query_study import fixture_service,DEFAULT_CASES as CATALOG
from app.personalized import recommend_personalized
from app.rag.settings import RagSettings

ROOT=Path(__file__).resolve().parents[2]
DEFAULT_CASES=ROOT/'data/fixtures/agent_cases_v1.json'


def run_study(cases_path,output_dir):
    cases_path,output_dir=Path(cases_path).resolve(),Path(output_dir).resolve()
    if output_dir==cases_path.parent or output_dir in cases_path.parents or cases_path.parent in output_dir.parents:
        raise ValueError('Output overlaps fixtures')
    if output_dir.exists():
        previous=artifact_io.verify_artifacts(output_dir,'experiment_manifest.json')
        if previous['experiment_id']!='agent_v1':raise ValueError('Unrelated output directory')
    fixture=json.loads(cases_path.read_text(encoding='utf-8'))
    catalog=json.loads(CATALOG.read_text(encoding='utf-8'))
    traces=[]
    with tempfile.TemporaryDirectory(prefix='agent-study-') as temporary:
        root=Path(temporary)
        dataset,serving=fixture_service(catalog,root/'dataset')
        for case in fixture['cases']:
            events=EventRepository(root/(case['id']+'-events.sqlite3'))
            sessions=SessionRepository(root/(case['id']+'-sessions.sqlite3'))
            def recommend(request):
                response=recommend_personalized(request,dataset,serving)
                response.metadata['request_id']=events.record_exposure(request,response)
                return response
            service=AgentService(recommend=recommend,events=lambda:events,
                reviews=dataset.load_representative_reviews_by_business,settings=lambda:RagSettings(),
                planner_provider=lambda s:(_ for _ in ()).throw(AssertionError('No model calls in offline study')))
            session=sessions.create({'latitude':0,'longitude':0,'city':'Tampa','radius_km':50,
                'max_price_level':4,'top_k':5,'user_id':'demo'})
            for index,step in enumerate(case['turns']):
                payload={'turn_id':str(index),'expected_version':index,'message':step['message'],
                         'use_model':False,'generate_answer':False}
                reply=sessions.turn(session['session_id'],payload,lambda state:service.execute(session['session_id'],payload,state))
                errors=[]
                if reply['status']!=step['status']:errors.append('status')
                if step.get('action',reply['action'])!=reply['action']:errors.append('action')
                slots=reply['state']['slots']
                for expected,key in [('include','include'),('exclude','exclude'),('topics','topics'),
                                      ('price','max_price_level'),('radius','radius_km')]:
                    if expected in step and step[expected]!=slots[key]:errors.append(expected)
                if step.get('empty') and reply['recommendations']:errors.append('unexpected_results')
                count=events.metrics()['event_counts']['favorite']
                if 'favorite_count' in step and count!=step['favorite_count']:errors.append('favorite_count')
                if step.get('retry'):
                    repeated=sessions.turn(session['session_id'],payload,lambda _:(_ for _ in ()).throw(AssertionError('Idempotent turn executed again')))
                    if repeated!=reply:errors.append('retry_changed_response')
                    if events.metrics()['event_counts']['favorite']!=count:errors.append('duplicate_write')
                if len(reply['trace'])>4 or reply['budget']['provider_calls']:errors.append('budget')
                for rec in reply['recommendations']:
                    if rec['price_level']>slots['max_price_level'] or rec['distance_km']>slots['radius_km']+.001:
                        errors.append('hard_constraint')
                if reply['answer']:
                    allowed={r['business_id'] for r in reply['recommendations']}
                    reviews=dataset.load_representative_reviews_by_business()
                    for citation in reply['answer']['citations']:
                        owned=[r for r in reviews.get(citation['business_id'],[]) if r['review_id']==citation['review_id']]
                        if citation['business_id'] not in allowed or not any(citation['excerpt'] in r['text'] for r in owned):
                            errors.append('citation')
                traces.append({'scenario':case['id'],'turn':index+1,'status':reply['status'],'action':reply['action'],
                    'slots':slots,'returned_ids':[r['business_id'] for r in reply['recommendations']],
                    'focused_business_id':reply['focused_business_id'],'favorite_events':count,
                    'tools':[{k:v for k,v in t.items() if k in ('tool','status','write')} for t in reply['trace']],
                    'provider_calls':reply['budget']['provider_calls'],'errors':sorted(set(errors))})
    report={'experiment_id':'agent_v1','scenarios':len(fixture['cases']),
            'scenario_passed':sum(not any(t['errors'] for t in traces if t['scenario']==c['id']) for c in fixture['cases']),
            'steps':len(traces),'steps_passed':sum(not t['errors'] for t in traces),
            'provider_calls':sum(t['provider_calls'] for t in traces),'scope':fixture['scope'],
            'claims':'functional state/tool/write/grounding contracts only; not open-ended dialogue quality'}
    output_dir.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.agent-',dir=output_dir.parent) as temporary:
        stage=Path(temporary)
        for name,value in [('metrics.json',report),('case_results.json',traces)]:
            (stage/name).write_text(json.dumps(value,ensure_ascii=False,sort_keys=True,indent=2)+'\n',encoding='utf-8')
        manifest={'experiment_id':'agent_v1','cases_sha256':artifact_io.file_sha256(cases_path),
            'catalog_fixture_sha256':artifact_io.file_sha256(CATALOG),
            'code_sha256':{str(p.relative_to(ROOT)).replace('\\','/'):artifact_io.file_sha256(p) for p in sorted((ROOT/'app').rglob('*.py'))}}
        artifact_io.publish_directory(stage,output_dir,manifest,'experiment_manifest.json')
    return report


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cases',type=Path,default=DEFAULT_CASES)
    parser.add_argument('--output-dir',type=Path,default=ROOT/'data/derived/agent_v1_acceptance')
    args=parser.parse_args(argv)
    report=run_study(args.cases,args.output_dir)
    print(json.dumps(report,ensure_ascii=False,indent=2))
    return 0 if report['scenario_passed']==report['scenarios'] else 1


if __name__=='__main__':raise SystemExit(main())
