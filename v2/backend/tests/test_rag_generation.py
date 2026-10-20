import json

import httpx
import pytest

from app.models import RecommendationRequest
from test_rag_context import response


def request():return RecommendationRequest(query='安静的咖啡店',user_id='private-user',latitude=27,longitude=-82)
REVIEWS={'b':[{'business_id':'b','review_id':'r','text':'Not quiet. Good coffee.'}]}


def plan():return {'items':[{'business_id':'b','fact_ids':['b1_distance','b1_price'],'citation_ids':['b1_c1']}]}


def test_valid_deepseek_contract_and_grounded_rendering():
    from app.rag.generation import AnswerService,DeepSeekProvider
    from app.rag.settings import RagSettings
    settings=RagSettings(api_key='private-api-key')
    def handle(req):
        assert req.url==httpx.URL('https://api.deepseek.com/chat/completions')
        assert req.headers['authorization']=='Bearer private-api-key'
        body=json.loads(req.content)
        assert body['response_format']=={'type':'json_object'} and body['thinking']=={'type':'disabled'}
        assert 'private-user' not in json.dumps(body) and 'private-api-key' not in json.dumps(body)
        return httpx.Response(200,json={'choices':[{'finish_reason':'stop','message':{'content':json.dumps(plan()),'reasoning_content':'must not expose'}}],
                                       'usage':{'prompt_tokens':10,'completion_tokens':20}})
    answer=AnswerService(settings,DeepSeekProvider(settings,transport=httpx.MockTransport(handle))).generate(request(),response(),REVIEWS)
    assert answer['mode']=='deepseek_plan' and answer['status']=='generated'
    assert 'Not quiet.' in answer['text'] and '不能保证' in answer['text']
    assert answer['citations'][0]['review_id']=='r'
    assert 'private-api-key' not in json.dumps(answer) and 'must not expose' not in json.dumps(answer)


@pytest.mark.parametrize('bad',[
    {'items':[{'business_id':'outside','fact_ids':[],'citation_ids':[]}]},
    {'items':[{'business_id':'b','fact_ids':['invented'],'citation_ids':['b1_c1']}]},
    {'items':[{'business_id':'b','fact_ids':['b1_price'],'citation_ids':['foreign-review']}]},
    {'items':[{'business_id':'b','fact_ids':['b1_price'],'citation_ids':[]}]},
    {'items':[]},
    {'items':[{'business_id':'b','fact_ids':['b1_price'],'citation_ids':['b1_c1'],'explanation':'This place is quiet!'}]},
    {'items':[{'business_id':'b','fact_ids':['b1_price'],'citation_ids':['b1_c1']}],'answer':'invented prose'},
])
def test_invalid_plan_cannot_introduce_facts_citations_or_merchants(bad):
    from app.rag.generation import AnswerService,DeepSeekProvider
    from app.rag.settings import RagSettings
    settings=RagSettings(api_key='private-key')
    transport=httpx.MockTransport(lambda _:httpx.Response(200,json={'choices':[{'finish_reason':'stop','message':{'content':json.dumps(bad)}}]}))
    answer=AnswerService(settings,DeepSeekProvider(settings,transport=transport)).generate(request(),response(),REVIEWS)
    assert answer['mode']=='template' and answer['reason']=='invalid_model_plan'
    assert 'quiet!' not in answer['text'] and 'invented prose' not in answer['text']


@pytest.mark.parametrize('case,reason',[('timeout','provider_timeout'),('rate','rate_limited'),('auth','authentication_failed'),('empty','invalid_provider_response'),('truncated','invalid_provider_response'),('oversize','provider_response_too_large')])
def test_provider_errors_are_sanitized_and_fall_back(case,reason):
    from app.rag.generation import AnswerService,DeepSeekProvider
    from app.rag.settings import RagSettings
    settings=RagSettings(api_key='never-expose-secret')
    def handle(req):
        if case=='timeout':raise httpx.ReadTimeout('never-expose-secret',request=req)
        if case in ('rate','auth'):return httpx.Response(429 if case=='rate' else 401,text='never-expose-secret')
        if case=='oversize':return httpx.Response(200,content=b'x'*70000)
        return httpx.Response(200,json={'choices':[{'finish_reason':'length' if case=='truncated' else 'stop','message':{'content':json.dumps(plan()) if case=='truncated' else ''}}]})
    answer=AnswerService(settings,DeepSeekProvider(settings,transport=httpx.MockTransport(handle))).generate(request(),response(),REVIEWS)
    assert answer['mode']=='template' and answer['reason']==reason
    assert 'never-expose-secret' not in json.dumps(answer)


def test_no_key_no_results_and_clarification_never_call_provider():
    from app.rag.generation import AnswerService
    from app.rag.settings import RagSettings
    class Never:
        def complete(self,*args):raise AssertionError('must not call')
    service=AnswerService(RagSettings(),Never())
    assert service.generate(request(),response(),REVIEWS)['reason']=='missing_key'
    empty=response();empty.recommendations=[]
    assert service.generate(request(),empty,REVIEWS)['status']=='no_candidates'
    req=request().model_copy(update={'query':'预算20元'})
    assert service.generate(req,empty,REVIEWS)['status']=='needs_clarification'
