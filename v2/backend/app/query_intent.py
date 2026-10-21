"""Small, explicit bilingual query grammar; unsupported constraints stay visible."""

import re
from dataclasses import asdict, dataclass, field


CATEGORIES = {
    'coffee': ('coffee', 'cafe', 'cafes', '咖啡'),
    'pizza': ('pizza', '披萨', '比萨'),
    'chinese': ('chinese', '中餐', '中国菜'),
    'japanese': ('japanese', '日本菜', '日料'),
    'sushi': ('sushi', '寿司'),
    'mexican': ('mexican', '墨西哥菜'),
    'thai': ('thai', '泰餐', '泰国菜'),
    'italian': ('italian', '意大利菜'),
    'burgers': ('burger', 'burgers', '汉堡'),
    'seafood': ('seafood', '海鲜'),
    'breakfast': ('breakfast', 'brunch', '早餐', '早午餐'),
    'vegan': ('vegan', '纯素'),
    'vegetarian': ('vegetarian', '素食'),
}
SOFT_TOPICS = {
    'quiet': ('quiet', 'calm', 'peaceful', '安静'),
    'conversation': ('conversation', 'chat', '聊天'),
    'date': ('romantic', 'date night', 'for a date', 'on a date', 'date spot', '约会', '浪漫'),
    'outdoor': ('outdoor', 'patio', '露天', '户外'),
    'formal': ('upscale', 'elegant', 'formal', 'fine dining', '体面', '正式', '有档次'),
    'hosting': ('special occasion', 'celebration', 'dinner party', '请客', '宴请', '聚餐'),
    'family': ('family friendly', 'kid friendly', '亲子', '带娃'),
    'work': ('wifi', 'laptop', 'study', '办公', '学习'),
    'parking': ('parking', '停车'),
    'value': ('value for money', 'affordable', '性价比', '实惠'),
}
STOPWORDS = set('a an the i want would like please find me restaurant restaurants food place nearby recommend within km price level no not without only and or for to with eat'.split())
NEGATION = r'(?:不要|不吃|排除|除了|不想吃|不喝|不含|\bno\b|\bnot\b|\bwithout\b|\bexclude\b)'


def alias_pattern(alias):
    return re.escape(alias) if re.search(r'[\u4e00-\u9fff]', alias) else r'\b' + re.escape(alias) + r'\b'


def contains(text, term):
    return re.search(alias_pattern(term), text.lower()) is not None


@dataclass
class QueryIntent:
    include_categories: list = field(default_factory=list)
    exclude_categories: list = field(default_factory=list)
    soft_topics: list = field(default_factory=list)
    radius_km: float | None = None
    max_price_level: int | None = None
    unresolved_constraints: list = field(default_factory=list)
    needs_clarification: bool = False
    lexical_terms: list = field(default_factory=list)

    @property
    def has_query_signal(self):
        return bool(self.include_categories or self.soft_topics or self.lexical_terms)

    def to_dict(self):
        return {**asdict(self), 'version': 'query_v1', 'category_operator': 'any_include_and_no_exclude',
                'has_query_signal': self.has_query_signal}


def parse_intent(query):
    text = query.lower()
    intent = QueryIntent()
    for clause in re.split(r'[,，;；。]|但是|但|\bbut\b', text):
        matches = sorted((m.start(), m.end(), key) for key, aliases in CATEGORIES.items()
                         for alias in aliases for m in re.finditer(alias_pattern(alias), clause))
        previous_end, negative = 0, False
        for start, end, key in matches:
            prefix = clause[previous_end:start]
            if re.search(NEGATION + r'\s*$', prefix):
                negative = True
            elif not re.fullmatch(r'\s*(?:和|或|以及|、|and|or)?\s*', prefix):
                negative = False
            target = intent.exclude_categories if negative else intent.include_categories
            if key not in target:
                target.append(key)
            previous_end = end
        for negative_clause in re.finditer(NEGATION + r'\s*([^,，;；。]+)', clause):
            remainder = negative_clause.group(1)
            if not any(re.match(alias_pattern(a), remainder) for aliases in CATEGORIES.values() for a in aliases):
                intent.unresolved_constraints.append('unrecognized_exclusion')
    for key, aliases in SOFT_TOPICS.items():
        if any(contains(text, alias) for alias in aliases):
            if any(re.search(r'(?:不要|不想|不|\bnot\b|\bno\b)\s*' + alias_pattern(alias), text) for alias in aliases):
                intent.unresolved_constraints.append('negated_soft_preference:' + key)
            else:
                intent.soft_topics.append(key)
    radii = [float(m) for m in re.findall(r'(\d+(?:\.\d+)?)\s*(?:公里|千米|\bkm\b)', text)]
    if radii:
        intent.radius_km = min(radii)
        if intent.radius_km <= 0:
            intent.unresolved_constraints.append('invalid_radius')
    prices = [int(m) for m in re.findall(r'(?:价格等级(?:不超过|上限|为)?|price\s+level\s*(?:<=|at most)?\s*)(\d+)', text)]
    if prices:
        intent.max_price_level = min(prices)
        if any(p not in (1, 2, 3, 4) for p in prices):
            intent.unresolved_constraints.append('invalid_price_level')
    # A recognized constraint introducer must have a fully recognized value;
    # never silently parse the integer prefix of decimals or another operator.
    for match in re.finditer(r'价格等级|price\s+level', text):
        suffix = text[match.end():]
        if not re.match(r'\s*(?:不超过|上限|为|<=|at most)?\s*\d+(?![\d.])', suffix):
            intent.unresolved_constraints.append('unsupported_price_expression')
    unsupported = {
        'currency_budget_not_price_level': r'\d+\s*(?:元|块|美元|dollars?|usd)|[$￥¥]\s*\d+',
        'allergy_not_verifiable': r'过敏|\ballerg\w*\b',
        'current_hours_unavailable': r'现在营业|此刻营业|\bopen now\b',
        'dietary_guarantee_unavailable': r'无麸质|不含麸质|不含花生|\bgluten.free\b|\bhalal\b|清真',
        'unsupported_limit_operator': r'(?:至少|大于|(?<!不)超过|不低于|\bat least\b|\bmore than\b|\bbeyond\b|\boutside\b|[><=])\s*\d+\s*(?:公里|千米|km)|\d+\s*(?:公里|千米)外|价格等级不低于|price\s+level\s*(?:>=|at least)',
        'unsupported_distance_expression': r'\d+\s*(?:米|\bm\b|\bmeters?\b|\bmiles?\b|\bmi\b)|\bbetween\b.*\bkm\b|\d+\s*(?:到|至|-|and)\s*\d+\s*(?:公里|千米|km)|-\s*\d+\s*(?:公里|千米|km)|[一二三四五六七八九十两]+\s*(?:公里|千米)',
    }
    for reason, pattern in unsupported.items():
        if re.search(pattern, text):
            intent.unresolved_constraints.append(reason)
    if set(intent.include_categories) & set(intent.exclude_categories):
        intent.unresolved_constraints.append('category_conflict')
    if not intent.include_categories and not intent.exclude_categories and re.search(r'想吃|必须|不要|只要|\bonly\b|\bwithout\b|\bno\b', text):
        intent.unresolved_constraints.append('unrecognized_explicit_requirement')
    excluded_terms = {alias for key in intent.exclude_categories for alias in CATEGORIES[key]}
    intent.lexical_terms = sorted(set(re.findall(r'[a-z][a-z0-9]+', text)) - STOPWORDS - excluded_terms)
    intent.include_categories.sort()
    intent.exclude_categories.sort()
    intent.soft_topics.sort()
    intent.unresolved_constraints = sorted(set(intent.unresolved_constraints))
    intent.needs_clarification = bool(intent.unresolved_constraints)
    return intent


def resolve_request(request, intent):
    return request.model_copy(update={
        'radius_km': min(request.radius_km, intent.radius_km) if intent.radius_km is not None else request.radius_km,
        'max_price_level': min(request.max_price_level, intent.max_price_level) if intent.max_price_level is not None else request.max_price_level,
    })


def matches_categories(business, intent):
    text = ' '.join(business.get('categories_normalized', [])).lower()
    matched = {key for key, aliases in CATEGORIES.items() if any(contains(text, a) for a in aliases)}
    return (not intent.include_categories or bool(matched & set(intent.include_categories))) and not bool(matched & set(intent.exclude_categories))


def expanded_terms(intent):
    terms = set(intent.lexical_terms)
    for key in intent.include_categories:
        terms.update(CATEGORIES[key])
    for key in intent.soft_topics:
        terms.update(SOFT_TOPICS[key])
    return sorted(terms)
