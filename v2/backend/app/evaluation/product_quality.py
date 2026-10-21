"""Run fixed natural-language cases through the real account-owned product API."""
import argparse
import hashlib
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from uuid import uuid4

from fastapi.testclient import TestClient

from app.agent.store import SessionRepository
from app.events import EventRepository
from app.product.accounts import AccountStore


ROOT=Path(__file__).resolve().parents[2]
DEFAULT_CASES=ROOT/'data/fixtures/product_quality_cases_v1.json'


def check_case(case,response):
    errors=[]
    if response['status']!=case['status']:errors.append('status')
    if 'action' in case and response['action']!=case['action']:errors.append('action')
    slots=response['state']['slots']
    for expected,key,label in [('include','include','include'),('exclude','exclude','exclude'),
                                ('topics','topics','topics'),('price','max_price_level','price'),
                                ('radius','radius_km','radius')]:
        if expected in case and slots[key]!=case[expected]:errors.append(label)
    if response.get('budget',{}).get('provider_calls',0):errors.append('unexpected_model_call')
    if response['status']=='needs_clarification' and response['recommendations']:
        errors.append('recommendations_during_clarification')
    for item in response['recommendations']:
        if item['distance_km']>slots['radius_km']+.001 and 'distance_constraint' not in errors:
            errors.append('distance_constraint')
        if item['price_level']>slots['max_price_level'] and 'price_constraint' not in errors:
            errors.append('price_constraint')
    return sorted(errors)


def run_study(cases_path,output_dir):
    import app.main as main

    cases_path,output_dir=Path(cases_path).resolve(),Path(output_dir).resolve()
    fixture=json.loads(cases_path.read_text(encoding='utf-8'))
    if fixture['version']!='product_quality_v1':raise ValueError('Unsupported case fixture')
    dataset=main.dataset_repository.load_manifest()
    rows=[]
    with TemporaryDirectory(prefix='product-quality-') as temporary:
        root=Path(temporary)
        accounts=AccountStore(root/'accounts.sqlite3')
        agents=SessionRepository(root/'sessions.sqlite3')
        events=EventRepository(root/'events.sqlite3')
        environment={'CAMPUSFOOD_MODE':'product','CAMPUSFOOD_COOKIE_SECURE':'false','DEEPSEEK_API_KEY':''}
        with patch.dict(os.environ,environment),patch.object(main,'get_product_account_store',lambda:accounts),\
             patch.object(main,'get_agent_repository',lambda:agents),\
             patch.object(main,'get_event_repository',lambda:events):
            client=TestClient(main.app)
            registered=client.post('/api/v2/product/register',json={
                'handle':'quality_runner','password':'isolated-quality-pass-2026'})
            if registered.status_code!=201:raise RuntimeError(f'Registration failed: {registered.status_code}')
            csrf={'X-CSRF-Token':registered.json()['csrf_token']}
            for case in fixture['cases']:
                created=client.post('/api/v2/product/sessions',headers=csrf,json={
                    'city':'Tampa','latitude':27.9506,'longitude':-82.4572,
                    'radius_km':5,'max_price_level':4,'top_k':5})
                if created.status_code!=201:raise RuntimeError(f'Session creation failed: {created.status_code}')
                sid=created.json()['session_id']
                sent=client.post(f'/api/v2/product/sessions/{sid}/turns',headers=csrf,json={
                    'turn_id':str(uuid4()),'expected_version':0,'message':case['message'],
                    'use_model':False,'generate_answer':False})
                if sent.status_code!=200:
                    rows.append({'id':case['id'],'message':case['message'],'http_status':sent.status_code,
                                 'errors':['product_api_error']})
                    continue
                reply=sent.json()
                rows.append({'id':case['id'],'message':case['message'],'expected_status':case['status'],
                    'status':reply['status'],'action':reply['action'],'slots':reply['state']['slots'],
                    'returned_ids':[item['business_id'] for item in reply['recommendations']],
                    'provider_calls':reply['budget']['provider_calls'],'errors':check_case(case,reply)})
    report={'experiment_id':'product_quality_v1','cases':len(rows),
            'passed':sum(not row['errors'] for row in rows),'failed_ids':[row['id'] for row in rows if row['errors']],
            'provider_calls':sum(row.get('provider_calls',0) for row in rows),
            'scope':fixture['scope'],'data_version':dataset['data_version'],
            'claims':'Curated real product API requests with installed Tampa data and rules mode. No DeepSeek calls; no blind human relevance judgments.'}
    output_dir.mkdir(parents=True,exist_ok=True)
    (output_dir/'metrics.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    (output_dir/'case_results.json').write_text(json.dumps(rows,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    (output_dir/'manifest.json').write_text(json.dumps({'experiment_id':report['experiment_id'],
        'cases_sha256':hashlib.sha256(cases_path.read_bytes()).hexdigest(),
        'data_version':dataset['data_version']},ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    return report


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cases',type=Path,default=DEFAULT_CASES)
    parser.add_argument('--output-dir',type=Path,default=ROOT/'data/derived/product_quality_v1_acceptance')
    args=parser.parse_args(argv)
    result=run_study(args.cases,args.output_dir)
    print(json.dumps(result,ensure_ascii=False,indent=2))
    return 0 if result['passed']==result['cases'] else 1


if __name__=='__main__':raise SystemExit(main())
