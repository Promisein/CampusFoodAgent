"""Deterministic slot updates and references; models cannot override these rules."""
from copy import deepcopy
import re

from app.query_intent import CATEGORIES, SOFT_TOPICS, contains, parse_intent


class Clarification(ValueError):
    pass


def initial_state(context):
    return {'context':dict(context), 'slots':{'include':[], 'exclude':[], 'topics':[], 'terms':[],
            'radius_km':context.get('radius_km',5), 'max_price_level':context.get('max_price_level',4)},
            'last_response':None, 'last_request':None, 'focus_business_id':None,
            'pending_clarification':False, 'messages':[]}


def action_for_message(message):
    text=message.strip()
    if re.fullmatch(r'(?:查看|我的)?收藏(?:列表|夹)?[。.!！]?',text) or text.lower() in ('show favorites','my favorites'):
        return {'action':'favorites'}
    if re.fullmatch(r'(?:查看)?历史(?:记录)?[。.!！]?',text) or text.lower()=='show history':
        return {'action':'history'}
    if re.search(r'收藏|\bfavorite\b|\bsave\b',text,re.I):
        reference=r'(?:第?[一二三四五1-5]+(?:家|个)?|它|这家|it|that one|the (?:first|second|third|fourth|fifth)(?: one)?)'
        if re.fullmatch(r'(?:请|帮我)?\s*(?:收藏|favorite|save)\s*'+reference+r'[。.!！\s]*',text,re.I):
            return {'action':'favorite'}
        if re.fullmatch(r'(?:请)?把'+reference+r'(?:收藏|加入收藏)(?:起来)?[。.!！\s]*',text):
            return {'action':'favorite'}
        return {'action':'clarify'}
    if re.search(r'解释|为什么|介绍|\bwhy\b|\bexplain\b',text,re.I):
        return {'action':'explain'}
    return {'action':'search'}


def merge_slots(state,message):
    slots=deepcopy(state['slots'])
    if re.search(r'换到|城市|坐标|定位|纽约|上海|\blatitude\b|\blongitude\b|\bcity\b',message,re.I):
        raise Clarification('更换位置请新建会话并填写城市与坐标。')
    removal=re.fullmatch(r'取消(.+?)(?:要求|偏好)?[。.!！]?',message.strip())
    if removal:
        topics=[k for k,aliases in SOFT_TOPICS.items() if removal[1].strip().lower() in aliases]
        if topics:
            slots['topics']=[k for k in slots['topics'] if k not in topics]
            removed_tokens={token for k in topics for alias in SOFT_TOPICS[k] for token in re.findall(r'[a-z][a-z0-9]+',alias)}
            slots['terms']=[term for term in slots['terms'] if term not in removed_tokens]
            return slots
    remove_exclusion=re.fullmatch(r'取消排除(.+?)[。.!！]?',message.strip())
    if remove_exclusion:
        keys=[k for k,aliases in CATEGORIES.items() if remove_exclusion[1].strip().lower() in aliases]
        if keys:
            slots['exclude']=[k for k in slots['exclude'] if k not in keys]
            return slots
    if message.strip().startswith('取消'):
        raise Clarification('一次请只取消一个明确条件，例如取消户外要求或取消排除披萨。')
    intent=parse_intent(message)
    if intent.needs_clarification:
        raise Clarification('这些条件暂时无法可靠确认：'+', '.join(intent.unresolved_constraints)+'。请改用价格等级、公里半径或明确类别。')
    cheaper=bool(re.search(r'便宜(?:一?点|一些)|\bcheaper\b',message,re.I))
    nearer=bool(re.search(r'近(?:一?点|一些)|\bcloser\b',message,re.I))
    if not (intent.has_query_signal or intent.exclude_categories or intent.radius_km is not None or
            intent.max_price_level is not None or cheaper or nearer or re.search(r'附近|推荐|\bnearby\b',message,re.I)):
        raise Clarification('请说明类别或偏好，例如咖啡、户外座位、再便宜一点。')
    if intent.include_categories:
        replace=bool(re.search(r'换成|改成|改为|改吃|\binstead\b|\bswitch\b',message,re.I))
        slots['include']=intent.include_categories if replace else sorted(set(slots['include'])|set(intent.include_categories))
        # Preserve lexical terms only for unrestricted first searches. Recognized
        # categories have an explicit bilingual canonical form.
        slots['terms']=[]
    elif not slots['include'] and intent.lexical_terms and not cheaper and not nearer:
        recognized={token for aliases in list(CATEGORIES.values())+list(SOFT_TOPICS.values())
                    for alias in aliases for token in re.findall(r'[a-z][a-z0-9]+',alias)}
        slots['terms']=sorted((set(slots['terms'])|set(intent.lexical_terms))-recognized)[:20]
    slots['exclude']=sorted(set(slots['exclude'])|set(intent.exclude_categories))
    slots['topics']=sorted(set(slots['topics'])|set(intent.soft_topics))
    if set(slots['include']) & set(slots['exclude']):
        raise Clarification('类别同时被要求和排除，请先取消对应排除条件或换一个类别。')
    if intent.radius_km is not None:slots['radius_km']=intent.radius_km
    if intent.max_price_level is not None:slots['max_price_level']=intent.max_price_level
    if cheaper:slots['max_price_level']=max(1,slots['max_price_level']-1)
    if nearer:slots['radius_km']=min(slots['radius_km'],max(.1,slots['radius_km']/2))
    if not 0 < slots['radius_km'] <= 50:raise Clarification('半径需要在0到50公里之间。')
    return slots


def query_for_slots(slots):
    pieces=[CATEGORIES[k][0] for k in slots['include']]
    pieces += ['not '+CATEGORIES[k][0] for k in slots['exclude']]
    pieces += [SOFT_TOPICS[k][0] for k in slots['topics']]
    pieces += slots['terms']
    pieces += [f"within {slots['radius_km']:g} km",f"price level {slots['max_price_level']}"]
    return ', '.join(pieces)


def resolve_reference(state,message):
    rows=(state.get('last_response') or {}).get('recommendations',[])
    if state.get('pending_clarification') or not rows:
        raise Clarification('请先完成一次有效搜索，再指定当前结果中的餐厅。')
    digits={'一':1,'二':2,'三':3,'四':4,'五':5,'六':6,'七':7,'八':8,'九':9,'十':10}
    matches=re.findall(r'第\s*([一二三四五六七八九十\d]+)\s*(?:家|个|条)?',message)
    indexes=[]
    for token in matches:
        indexes.append(int(token) if token.isdigit() else digits.get(token,99))
    for number,word in enumerate(('first','second','third','fourth','fifth'),1):
        if re.search(r'\b'+word+r'\b',message,re.I):indexes.append(number)
    indexes += [int(v) for v in re.findall(r'\b(?:number|restaurant)\s*(\d+)\b',message,re.I)]
    if len(set(indexes))>1:raise Clarification('一次请只指定一家餐厅。')
    if indexes:
        if not 1 <= indexes[0] <= len(rows):raise Clarification('序号不在当前结果中，请重新选择。')
        return rows[indexes[0]-1]['business_id']
    focus=state.get('focus_business_id')
    if re.search(r'它|这家|\bit\b|that one',message,re.I):
        if focus in {r['business_id'] for r in rows}:return focus
        if len(rows)==1:return rows[0]['business_id']
    raise Clarification('请明确指定当前列表中的序号，例如第二家。')
