import json

import httpx

from app.evidence import retrieve_evidence
from app.query_intent import parse_intent
from app.rag.context import retrieve_sentences


def test_cards_and_rag_share_same_bm25_order_and_cues():
    rows = [
        {'business_id': 'a', 'review_id': 'r1', 'text': 'This is not quiet. Coffee.'},
        {'business_id': 'a', 'review_id': 'r2', 'text': 'A quiet peaceful cafe.'},
        {'business_id': 'other', 'review_id': 'r3', 'text': 'Quiet.'},
    ]
    intent = parse_intent('安静咖啡')
    card = retrieve_evidence('a', '安静咖啡', intent, rows)
    rag = retrieve_sentences('a', rows, intent)
    assert [(c['document_id'], c['excerpt'], c['cue']) for c in card['items']] == [
        (c['review_id'], c['excerpt'], c['cue']) for c in rag]
    assert card['status'] == 'mixed_cues'


def test_duplicate_review_id_keeps_quote_with_matching_source_text():
    rows=[{'business_id':'b','review_id':'r','source':'first','text':'Quiet peaceful cafe.'},
          {'business_id':'b','review_id':'r','source':'second','text':'Pizza only.'}]
    result=retrieve_evidence('b','quiet',parse_intent('quiet'),rows)['items'][0]
    assert result['excerpt'] in result['text']
    assert result['source']=='first'


def test_soft_topic_phrase_does_not_match_generic_night_or_split_across_sentence():
    rows=[{'business_id':'b','review_id':'unrelated','text':'Friday night was busy. The short rib was good.'},
          {'business_id':'b','review_id':'split','text':'What a date. Night was busy.'},
          {'business_id':'b','review_id':'true','text':'A romantic atmosphere for a date night.'},
          {'business_id':'b','review_id':'date','text':'A good spot for a date or casual dining.'}]
    citations=retrieve_sentences('b',rows,parse_intent('romantic italian'),limit=10)
    assert {c['review_id'] for c in citations}=={'true','date'}
    assert all(c['matched_terms'] for c in citations)


def test_selected_subset_links_same_card_quotes_and_uncovered_stays_unnumbered(tmp_path, monkeypatch):
    import app.main as main
    from app.models import EvidenceItem, RecommendationRequest
    from app.rag.generation import AnswerService, DeepSeekProvider
    from app.rag.settings import RagSettings
    from test_rag_context import response
    from app.rag.context import default_plan

    result = response()
    result.recommendations.append(result.recommendations[0].model_copy(deep=True, update={'business_id': 'c'}))
    reviews = {'b': [
        {'business_id': 'b', 'review_id': 'r1', 'text': 'Quiet place.'},
        {'business_id': 'b', 'review_id': 'r2', 'text': 'Quiet and peaceful.'},
    ]}
    req = RecommendationRequest(query='安静', latitude=0, longitude=0)
    for rec in result.recommendations:
        evidence = retrieve_evidence(rec.business_id, req.query, parse_intent(req.query), reviews.get(rec.business_id, []))
        rec.evidence = [EvidenceItem(**e) for e in evidence['items']]
    settings = RagSettings(api_key='mock', max_restaurants=1)
    def handler(request):
        context = json.loads(json.loads(request.content)['messages'][1]['content'])['untrusted_context']
        plan = default_plan(context)
        plan['items'][0]['citation_ids'] = plan['items'][0]['citation_ids'][1:]
        return httpx.Response(200, json={'choices': [{'finish_reason': 'stop', 'message': {'content': json.dumps(plan)}}]})
    monkeypatch.setattr(main, 'get_rag_service', lambda: AnswerService(settings, DeepSeekProvider(settings, transport=httpx.MockTransport(handler))))
    monkeypatch.setattr(main.dataset_repository, 'load_representative_reviews_by_business', lambda: reviews)
    before = [(r.business_id, r.score) for r in result.recommendations]
    main.attach_answer(req, result)
    assert result.answer['mode'] == 'deepseek_plan'
    assert [(r.business_id, r.score) for r in result.recommendations] == before
    evidence = result.recommendations[0].evidence
    assert [e.citation_id for e in evidence] == ['b1_c1', 'b1_c2']
    assert [e.used_in_answer for e in evidence] == [False, True]
    assert result.answer['citations'][0]['excerpt'] == evidence[1].excerpt
    assert result.metadata['answer_evidence_covered_business_ids'] == ['b']
