import pytest


def test_slots_inherit_refine_replace_and_remove_without_losing_constraints():
    from app.agent.state import initial_state, merge_slots, query_for_slots
    state=initial_state({'latitude':0,'longitude':0,'radius_km':5,'max_price_level':3})
    state['slots']=merge_slots(state,'找咖啡，不要披萨')
    assert state['slots']['include']==['coffee'] and state['slots']['exclude']==['pizza']
    state['slots']=merge_slots(state,'再便宜一点')
    assert state['slots']['max_price_level']==2
    state['slots']=merge_slots(state,'最好有户外座位')
    assert state['slots']['topics']==['outdoor'] and state['slots']['include']==['coffee']
    state['slots']=merge_slots(state,'换成中餐')
    assert state['slots']['include']==['chinese'] and state['slots']['exclude']==['pizza']
    state['slots']=merge_slots(state,'取消户外要求')
    assert state['slots']['topics']==[]
    assert 'not pizza' in query_for_slots(state['slots'])


@pytest.mark.parametrize('message',['50元以内','现在营业','不含花生，过敏','咖啡，不要咖啡','换到纽约','不要安静','取消户外要求，现在营业，50元以内','取消排除披萨，现在营业'])
def test_unsupported_conditions_do_not_mutate_slots(message):
    from app.agent.state import initial_state,merge_slots,Clarification
    state=initial_state({'latitude':0,'longitude':0})
    before=dict(state['slots'])
    with pytest.raises(Clarification):merge_slots(state,message)
    assert state['slots']==before


def test_actions_references_and_write_guard():
    from app.agent.state import action_for_message,resolve_reference,Clarification
    assert action_for_message('收藏第二家')['action']=='favorite'
    assert action_for_message('解释第二家')['action']=='explain'
    assert action_for_message('不要收藏第二家')['action']=='clarify'
    assert action_for_message('告诉我怎么收藏第二家')['action']=='clarify'
    state={'last_response':{'recommendations':[{'business_id':'a'},{'business_id':'b'}]},'focus_business_id':None,'pending_clarification':False}
    assert resolve_reference(state,'第二家')=='b'
    with pytest.raises(Clarification):resolve_reference(state,'它')
    state['focus_business_id']='b'
    assert resolve_reference(state,'它')=='b'
    state['pending_clarification']=True
    with pytest.raises(Clarification):resolve_reference(state,'第二家')


def test_cancel_english_topic_removes_it_from_canonical_query():
    from app.agent.state import initial_state,merge_slots,query_for_slots
    from app.query_intent import parse_intent
    state=initial_state({'latitude':0,'longitude':0})
    state['slots']=merge_slots(state,'quiet laptop')
    assert 'laptop' in state['slots']['terms']
    state['slots']=merge_slots(state,'取消安静要求')
    assert not parse_intent(query_for_slots(state['slots'])).soft_topics
