import pytest


def empty_state():
    from app.agent.state import initial_state
    return initial_state({'latitude':0,'longitude':0})


def plan(changes=(),issues=(),resolved=(),action='search'):
    return {'action':action,'index':None,'changes':list(changes),'issues':list(issues),'resolved':list(resolved)}


def test_screenshot_query_becomes_soft_preferences_without_forced_cuisine():
    from app.agent.semantic import interpret
    message='我想吃一个体面点的饭店，然后适合请客和约会'
    value=plan([{'field':'topics','op':'add','value':['formal','hosting','date'],'quote':'体面点的饭店，然后适合请客和约会'}])
    result=interpret(value,empty_state(),message)
    assert not result['issues'] and result['slots']['include']==[]
    assert result['slots']['topics']==['date','formal','hosting']


def test_hard_requirement_cannot_be_omitted_or_invented_by_model():
    from app.agent.semantic import interpret
    for message in ['人均100元','必须现在营业','花生过敏，绝不能含花生']:
        result=interpret(plan(),empty_state(),message)
        assert result['issues']
    with pytest.raises(ValueError):
        interpret(plan([{'field':'max_price_level','op':'set','value':4,'quote':'体面'}]),empty_state(),'体面')
    with pytest.raises(ValueError):
        interpret(plan([{'field':'topics','op':'add','value':['date'],'quote':'凭空引用'}]),empty_state(),'便宜点')
    with pytest.raises(ValueError):
        interpret(plan([{'field':'include','op':'set','value':['foreign_category'],'quote':'火星菜'}]),empty_state(),'火星菜')
    result=interpret(plan(),empty_state(),'咖啡，不要咖啡')
    assert result['issues']


def test_pending_budget_keeps_scene_and_requires_explicit_resolution():
    from app.agent.semantic import interpret
    state=empty_state()
    message='适合约会，人均100元'
    first=interpret(plan([{'field':'topics','op':'add','value':['date'],'quote':'约会'}]),state,message)
    assert first['issues']
    state['pending_semantic']={'slots':first['slots'],'issues':first['issues'],'source_text':message}
    unrelated=interpret(plan([{'field':'include','op':'set','value':['italian'],'quote':'意大利菜'}]),state,'意大利菜')
    assert unrelated['issues'] and unrelated['slots']['topics']==['date']
    final=interpret(plan([{'field':'max_price_level','op':'set','value':2,'quote':'价格等级2'}]),state,'那就价格等级2')
    assert not final['issues'] and final['slots']['topics']==['date'] and final['slots']['max_price_level']==2


def test_distance_conversion_and_explicit_filters_are_checked_in_code():
    from app.agent.semantic import interpret
    result=interpret(plan([{'field':'radius_km','op':'set','value':.5,'quote':'500米'}]),empty_state(),'500米以内，不要披萨')
    assert not result['issues'] and result['slots']['radius_km']==.5
    assert result['slots']['exclude']==['pizza']
    with pytest.raises(ValueError):
        interpret(plan([{'field':'radius_km','op':'set','value':5,'quote':'500米'}]),empty_state(),'500米以内')
    assert interpret(plan(),empty_state(),'方圆一百公里')['issues']


def test_current_money_is_not_resolved_merely_by_also_stating_price_level():
    from app.agent.semantic import interpret
    result=interpret(plan([{'field':'max_price_level','op':'set','value':2,'quote':'价格等级2'}]),empty_state(),'价格等级2，人均100元以内')
    assert any(i['code']=='currency_budget' for i in result['issues'])


def test_accepting_atmosphere_as_soft_does_not_cancel_allergy_or_live_requirements():
    from app.agent.semantic import interpret
    for message,code in [('花生过敏，但安静可以作为软偏好，我接受软偏好','dietary_guarantee'),
                         ('现在必须营业，但安静我接受软偏好','live_availability')]:
        assert any(i['code']==code for i in interpret(plan(),empty_state(),message)['issues'])


def test_explicit_filters_and_relative_direction_override_incorrect_model_patches():
    from app.agent.semantic import interpret
    with pytest.raises(ValueError):
        interpret(plan([{'field':'exclude','op':'remove','value':['pizza'],'quote':'不要披萨'}]),empty_state(),'咖啡，不要披萨')
    valid=interpret(plan([{'field':'topics','op':'add','value':['date'],'quote':'约会'}]),empty_state(),'咖啡，约会')
    assert valid['slots']['include']==['coffee']
    radius=interpret(plan([{'field':'radius_km','op':'set','value':5,'quote':'5 km'}]),empty_state(),'coffee within 1 km, within 5 km')
    assert radius['slots']['radius_km']==1
    state=empty_state();state['slots']['max_price_level']=2
    with pytest.raises(ValueError):
        interpret(plan([{'field':'price_delta','op':'set','value':1,'quote':'再便宜一点'}]),state,'再便宜一点')


def test_cancellation_cannot_cover_a_different_clause_or_exclusion_target():
    from app.agent.semantic import interpret
    result=interpret(plan(),empty_state(),'取消过敏保证，但不能放花生')
    assert any(i['code']=='dietary_guarantee' for i in result['issues'])
    with pytest.raises(ValueError):
        interpret(plan([{'field':'exclude','op':'remove','value':['pizza'],'quote':'不要披萨'}]),empty_state(),'咖啡，允许户外，不要披萨')


def test_chinese_decimal_distance_is_not_a_numeric_suffix():
    from app.agent.semantic import interpret,distance_values
    assert distance_values('零点五公里')==[.5]
    with pytest.raises(ValueError):
        interpret(plan([{'field':'radius_km','op':'set','value':5,'quote':'零点五公里'}]),empty_state(),'零点五公里以内')


def test_negated_permission_does_not_cancel_exclusion():
    from app.agent.semantic import interpret
    state=empty_state();state['slots'].update(include=['coffee'],exclude=['pizza'])
    for message in ['还是不允许披萨','允许披萨，但不要披萨']:
        with pytest.raises(ValueError):
            interpret(plan([{'field':'exclude','op':'remove','value':['pizza'],'quote':message}]),state,message)
    allowed=interpret(plan([{'field':'exclude','op':'remove','value':['pizza'],'quote':'允许披萨'}]),state,'允许披萨')
    assert not allowed['issues'] and allowed['slots']['exclude']==[]


def test_radius_patch_does_not_turn_minimum_or_negative_distance_into_ceiling():
    from app.agent.semantic import interpret
    for message,value in [('至少五公里',5),('-500米',.5)]:
        result=interpret(plan([{'field':'radius_km','op':'set','value':value,'quote':message}]),empty_state(),message)
        assert result['issues']


def test_semantic_api_retains_pending_scene_and_human_readable_prompts(tmp_path,monkeypatch):
    import json
    import httpx
    import app.main as main
    from app.rag.settings import RagSettings
    from app.rag.generation import DeepSeekProvider
    from test_agent_api import setup_agent,turn
    client,session,_=setup_agent(tmp_path,monkeypatch)
    settings=RagSettings(api_key='mock-semantic')
    def handler(request):
        context=json.loads(json.loads(request.content)['messages'][1]['content'])['untrusted_context']
        message=context['message']
        if message=='适合约会，人均100元':value=plan([{'field':'topics','op':'add','value':['date'],'quote':'约会'}])
        elif message=='那就价格等级2':value=plan([{'field':'max_price_level','op':'set','value':2,'quote':'价格等级2'}])
        else:value=plan([{'field':'topics','op':'add','value':['formal','hosting','date'],'quote':'体面点的饭店，然后适合请客和约会'}])
        return httpx.Response(200,json={'choices':[{'finish_reason':'stop','message':{'content':json.dumps(value)}}]})
    monkeypatch.setattr(main,'get_agent_settings',lambda:settings)
    monkeypatch.setattr(main,'get_agent_planner_provider',lambda s:DeepSeekProvider(s,transport=httpx.MockTransport(handler)))
    result,_=turn(client,session,'我想吃一个体面点的饭店，然后适合请客和约会',use_model=True)
    assert result['status']=='completed' and result['planner']['mode']=='deepseek_semantic'
    assert result['state']['slots']['include']==[] and set(result['state']['slots']['topics'])=={'formal','hosting','date'}
    blocked,_=turn(client,session,'适合约会，人均100元',use_model=True)
    assert blocked['status']=='needs_clarification' and '价格等级' in blocked['message'] and not blocked['recommendations']
    assert 'unrecognized_' not in blocked['message']
    recovered,_=turn(client,session,'那就价格等级2',use_model=True)
    assert recovered['status']=='completed' and 'date' in recovered['state']['slots']['topics']
    assert recovered['state']['slots']['max_price_level']==2


def test_rule_fallback_does_not_forget_unresolved_hard_requirement(tmp_path,monkeypatch):
    from test_agent_api import setup_agent,turn
    client,session,_=setup_agent(tmp_path,monkeypatch)
    turn(client,session,'咖啡')
    blocked,_=turn(client,session,'人均100元以内')
    assert blocked['status']=='needs_clarification'
    unrelated,_=turn(client,session,'改成意大利菜')
    assert unrelated['status']=='needs_clarification' and not unrelated['recommendations']
    assert '价格等级' in unrelated['message']
    recovered,_=turn(client,session,'价格等级2')
    assert recovered['status']=='completed' and recovered['state']['slots']['include']==['italian']


@pytest.mark.parametrize('use_model',[False,True])
@pytest.mark.parametrize('requirement,cancellation',[('人均100元','取消金额限制'),('花生过敏','不要求过敏安全保证')])
def test_explicit_cancellation_can_recover_without_semantic_provider(tmp_path,monkeypatch,use_model,requirement,cancellation):
    import app.main as main
    from app.rag.settings import RagSettings
    from test_agent_api import setup_agent,turn
    client,session,_=setup_agent(tmp_path,monkeypatch)
    class FailedProvider:
        def complete(self,context):raise ValueError('mock-provider-failure')
    monkeypatch.setattr(main,'get_agent_settings',lambda:RagSettings(api_key='mock-only'))
    monkeypatch.setattr(main,'get_agent_planner_provider',lambda _:FailedProvider())
    turn(client,session,'咖啡')
    blocked,_=turn(client,session,requirement,use_model=use_model)
    assert blocked['status']=='needs_clarification'
    invalid,_=turn(client,session,cancellation+'，现在营业',use_model=use_model)
    assert invalid['status']=='needs_clarification' and not invalid['recommendations']
    recovered,_=turn(client,session,cancellation+'，改为历史数据',use_model=use_model)
    assert recovered['status']=='completed' and recovered['state']['slots']['include']==['coffee']


def test_fallback_cancellation_cannot_hide_new_ingredient_requirement(tmp_path,monkeypatch):
    from test_agent_api import setup_agent,turn
    client,session,_=setup_agent(tmp_path,monkeypatch)
    turn(client,session,'咖啡')
    turn(client,session,'花生过敏')
    blocked,_=turn(client,session,'取消过敏安全保证，咖啡不能放花生')
    assert blocked['status']=='needs_clarification' and not blocked['recommendations']
    state=client.get('/api/v2/agent/sessions/'+session['session_id']).json()['state']
    assert any(i['code']=='dietary_guarantee' for i in state['pending_semantic']['issues'])
