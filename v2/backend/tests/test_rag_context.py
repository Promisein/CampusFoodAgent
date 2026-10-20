from app.models import RecommendationRequest,RecommendationResponse,RestaurantRecommendation


def response():
    return RecommendationResponse(version='v2',engine='fixture',recommendations=[RestaurantRecommendation(
        business_id='b',name='Cafe',city='Tampa',categories=['Coffee'],price_level=1,rating=4,
        review_count=10,distance_km=.5,score=.1,reasons=[],evidence=[])])


def test_context_bm25_quotes_owner_cues_and_no_private_request_data():
    from app.rag.context import build_context,render_plan,default_plan
    from app.rag.settings import RagSettings
    request=RecommendationRequest(query='安静的咖啡店',user_id='private-person',latitude=27.123456,longitude=-82.123456)
    reviews={'b':[{'review_id':'good','business_id':'b','text':'Very quiet coffee shop. Friendly staff.'},
                  {'review_id':'bad','business_id':'b','text':'It is not quiet. Good coffee.'},
                  {'review_id':'wrong','business_id':'other','text':'Quiet and peaceful.'}]}
    context=build_context(request,response(),reviews,RagSettings())
    import json
    serialized=json.dumps(context)
    assert 'private-person' not in serialized and '27.123456' not in serialized and '-82.123456' not in serialized
    citations=context['items'][0]['citations']
    assert {c['review_id'] for c in citations}=={'good','bad'}
    assert any(c['cue']=='negative_cue' for c in citations)
    assert all(c['business_id']=='b' for c in citations)
    text=render_plan(context,default_plan(context))
    assert 'Cafe' in text and '不能保证' in text
    assert all(c['excerpt'] in text for c in citations)


def test_no_relevant_quote_and_context_budget_are_explicit():
    from app.rag.context import build_context
    from app.rag.settings import RagSettings
    req=RecommendationRequest(query='安静',latitude=0,longitude=0)
    context=build_context(req,response(),{'b':[{'business_id':'b','review_id':'x','text':'Great pizza.'}]},RagSettings(max_context_chars=4000))
    assert not context['items'][0]['citations']
    assert context['items'][0]['evidence_status']=='insufficient'


def test_budget_overflow_does_not_claim_there_are_no_recommendations():
    import json
    from app.rag.generation import AnswerService
    from app.rag.context import build_context
    from app.rag.settings import RagSettings
    req=RecommendationRequest(query='安静',latitude=0,longitude=0)
    reviews={'b':[{'business_id':'b','review_id':'r'*5000,'text':'Quiet place.'}]}
    settings=RagSettings(max_context_chars=4000)
    context=build_context(req,response(),reviews,settings)
    assert len(json.dumps(context,ensure_ascii=False))<=4000
    answer=AnswerService(settings).generate(req,response(),reviews)
    assert answer['reason']=='context_budget'
    assert '没有符合' not in answer['text']
