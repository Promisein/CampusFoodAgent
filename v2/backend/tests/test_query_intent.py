import pytest

from app.models import RecommendationRequest


def request(query, **kwargs):
    return RecommendationRequest(query=query, latitude=0, longitude=0, **kwargs)


def test_bilingual_categories_exclusions_and_stricter_limits():
    from app.query_intent import parse_intent, resolve_request, matches_categories
    req = request('想吃披萨，不要咖啡，2公里内，价格等级不超过2，安静', radius_km=5)
    intent = parse_intent(req.query)
    assert intent.include_categories == ['pizza']
    assert intent.exclude_categories == ['coffee']
    assert intent.soft_topics == ['quiet']
    resolved = resolve_request(req, intent)
    assert (resolved.radius_km, resolved.max_price_level) == (2, 2)
    assert matches_categories({'categories_normalized': ['Pizza']}, intent)
    assert not matches_categories({'categories_normalized': ['Pizza', 'Coffee & Tea']}, intent)
    assert resolve_request(request('within 20 km, price level 4', radius_km=1, max_price_level=1), parse_intent('within 20 km, price level 4')).radius_km == 1


@pytest.mark.parametrize('query', ['必须披萨但不要披萨', '预算20元', 'peanut allergy', '现在营业', 'not quiet'])
def test_unresolvable_hard_requests_or_negated_soft_topics_are_explicit(query):
    from app.query_intent import parse_intent
    intent = parse_intent(query)
    assert intent.unresolved_constraints
    assert intent.needs_clarification


def test_word_boundaries_neutral_unknown_and_english_negation():
    from app.query_intent import parse_intent
    assert parse_intent('no pizza, coffee please').exclude_categories == ['pizza']
    assert parse_intent('no pizza, coffee please').include_categories == ['coffee']
    assert not parse_intent('pizzazz').include_categories
    assert not parse_intent('随便推荐').has_query_signal
    assert parse_intent('想吃火星菜').unresolved_constraints


@pytest.mark.parametrize('query', ['不要披萨和汉堡', 'no pizza or burgers'])
def test_coordinated_exclusions_apply_to_both_categories(query):
    from app.query_intent import parse_intent
    intent = parse_intent(query)
    assert intent.exclude_categories == ['burgers', 'pizza']
    assert not intent.include_categories


@pytest.mark.parametrize('query', ['披萨，不要香菜', 'pizza without peanuts', 'pizza at least 3 km away', '披萨3公里外', 'pizza price level 0', '价格等级不低于2的披萨'])
def test_unsupported_clause_is_not_silently_discarded(query):
    from app.query_intent import parse_intent
    assert parse_intent(query).needs_clarification


@pytest.mark.parametrize('query', ['pizza price level < 2', 'pizza price level > 2', '披萨 价格等级低于2',
                                   'pizza within 500 m', 'pizza between 2 and 5 km', '披萨2到5公里',
                                   'pizza price level 2.5', 'pizza -3 km', '披萨500米内', '披萨三公里内'])
def test_unsupported_numeric_grammar_requests_clarification(query):
    from app.query_intent import parse_intent
    assert parse_intent(query).needs_clarification


def test_supported_upper_bound_and_pure_exclusion_do_not_create_false_signal():
    from app.query_intent import parse_intent
    assert not parse_intent('披萨 半径不超过3公里').needs_clarification
    assert not parse_intent('no pizza').has_query_signal
