"""Merchant-scoped BM25 sentence retrieval and canonical grounded output."""
import json
import math
import re
from collections import Counter

from app.query_intent import SOFT_TOPICS,contains,expanded_terms,parse_intent


def retrieve_sentences(business_id,reviews,intent,*,limit=2):
    terms=sorted({t for topic in intent.soft_topics for t in SOFT_TOPICS[topic]}) if intent.soft_topics else expanded_terms(intent)
    tokens=sorted({t for term in terms for t in re.findall(r'[a-z][a-z0-9]+|[\u4e00-\u9fff]+',term.lower())})
    if not tokens:return []
    documents=[]
    for row in reviews:
        if row.get('business_id')!=business_id or not isinstance(row.get('text'),str) or not isinstance(row.get('review_id'),str):continue
        for sentence in re.split(r'(?<=[.!?。！？])\s*',row['text'][:40000]):
            sentence=sentence.strip()
            if not sentence:continue
            # A bounded verbatim substring; never invent a paraphrase as a quote.
            sentence=sentence[:500]
            bag=Counter(re.findall(r'[a-z][a-z0-9]+|[\u4e00-\u9fff]+',sentence.lower()))
            documents.append((row,sentence,bag))
    if not documents:return []
    average=sum(sum(bag.values()) for _,_,bag in documents)/len(documents)
    frequency={t:sum(t in bag for _,_,bag in documents) for t in tokens}
    ranked=[]
    for row,sentence,bag in documents:
        score=0.
        for t in tokens:
            tf=bag[t];idf=math.log1p((len(documents)-frequency[t]+.5)/(frequency[t]+.5))
            score+=idf*tf*2.2/(tf+1.2*(.25+.75*sum(bag.values())/max(average,1)))
        if score<=0:continue
        matched=[term for term in terms if contains(sentence,term)]
        negative=bool(re.search(r'\b(?:not|never|no|loud|noisy|crowded)\b|不安静|吵|嘈杂|并不|不适合',sentence.lower()))
        ranked.append({'business_id':business_id,'review_id':row['review_id'],'source':str(row.get('source','yelp_review'))[:80],
                       'excerpt':sentence,'score':score,'matched_terms':matched,
                       'cue':'negative_cue' if negative else 'mention_only'})
    ranked.sort(key=lambda r:(-r['score'],r['review_id'],r['excerpt']))
    # Distinct review sources, not two fragments falsely counted as corroboration.
    unique=[];seen=set()
    for row in ranked:
        if row['review_id'] not in seen:unique.append(row);seen.add(row['review_id'])
    return unique[:limit]


def build_context(request,response,reviews,settings):
    intent=parse_intent(request.query)
    context={'version':'rag_v1','query':request.query[:1000],
             'scope':'present Yelp snapshot; review relevance is not factual entailment',
             'soft_topics':intent.soft_topics,'needs_clarification':intent.needs_clarification,
             'total_recommendations':len(response.recommendations),'items':[]}
    for rec in response.recommendations[:settings.max_restaurants]:
        name=rec.name[:160]
        facts=[('name',f'名称：{name}。'),('distance',f'按数据坐标计算，距离请求位置约{rec.distance_km:.2f}公里。'),
               ('price',f'数据集价格等级为{rec.price_level}（不是金额）。'),
               ('rating',f'Yelp数据快照评分为{rec.rating:.1f}/5。'),
               ('category','数据集类别：'+'、'.join(c[:40] for c in rec.categories[:8])+'。')]
        n=len(context['items'])+1
        item={'business_id':rec.business_id,'name':name,
              'facts':[{'id':f'b{n}_{key}','text':text} for key,text in facts],
              'citations':retrieve_sentences(rec.business_id,reviews.get(rec.business_id,[]),intent)}
        for i,c in enumerate(item['citations'],1):c['id']=f'b{n}_c{i}'
        item['evidence_status']='related_mentions' if item['citations'] else 'insufficient'
        if any(c['cue']=='negative_cue' for c in item['citations']) and any(c['cue']=='mention_only' for c in item['citations']):
            item['evidence_status']='mixed_cues'
        context['items'].append(item)
        if len(json.dumps(context,ensure_ascii=False))>settings.max_context_chars:
            context['items'].pop();break
    context['covered_recommendations']=len(context['items'])
    context['query_truncated']=len(request.query)>1000
    while context['items'] and len(json.dumps(context,ensure_ascii=False))>settings.max_context_chars:
        context['items'].pop()
        context['covered_recommendations']=len(context['items'])
    return context


def default_plan(context):
    return {'items':[{'business_id':item['business_id'],'fact_ids':[f['id'] for f in item['facts']],
                      'citation_ids':[c['id'] for c in item['citations']]} for item in context['items']]}


def render_plan(context,plan):
    if context['needs_clarification']:return '目前无法可靠确认全部条件，请根据提示补充或调整条件后再试。'
    if not context['items']:
        return '本次已有推荐结果，但证据上下文超出预算，暂不生成说明；请查看餐厅卡片。' if context['total_recommendations'] else '没有符合已确认条件的餐厅，暂不生成推荐说明。'
    lines=[f"以下说明覆盖本次返回的前{len(context['items'])}家餐厅，保持推荐顺序："]
    for n,(item,selected) in enumerate(zip(context['items'],plan['items']),1):
        facts={f['id']:f['text'] for f in item['facts']};citations={c['id']:c for c in item['citations']}
        lines.append(f"{n}. {item['name']}")
        lines.extend(facts[key] for key in selected['fact_ids'])
        for key in selected['citation_ids']:
            c=citations[key];label='含否定线索的相关原文' if c['cue']=='negative_cue' else '相关评论原文'
            lines.append(f"{label} [{key}]：“{c['excerpt']}”")
        if context['soft_topics']:
            lines.append('评论仅为相关提及，不能保证真实环境满足需求；请核对原文中的否定或冲突描述。' if item['citations'] else '缺少关于本次软偏好的相关评论证据，不能保证满足该偏好。')
    lines.append('以上是历史数据快照；营业标记不代表现在营业，评论也不构成饮食或过敏安全保证。')
    return '\n'.join(lines)
