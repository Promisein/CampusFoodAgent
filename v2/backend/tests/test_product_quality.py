def test_product_case_checks_status_slots_and_hard_constraints():
    from app.evaluation.product_quality import check_case

    case={'id':'coffee','message':'找咖啡店','status':'completed','include':['coffee']}
    response={'status':'completed','action':'search','state':{'slots':{'include':['coffee'],
        'radius_km':5,'max_price_level':2}},'recommendations':[{'business_id':'A',
        'distance_km':6,'price_level':3}], 'budget':{'provider_calls':0}}
    assert check_case(case,response)==['distance_constraint','price_constraint']
    response['recommendations'][0].update(distance_km=1,price_level=1)
    assert check_case(case,response)==[]
    response['status']='needs_clarification'
    response['budget']['provider_calls']=1
    assert check_case(case,response)==['recommendations_during_clarification','status','unexpected_model_call']
