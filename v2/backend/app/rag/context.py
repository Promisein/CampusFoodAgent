"""Merchant-scoped BM25 sentence retrieval and canonical grounded output."""
import json

from app.query_intent import parse_intent
from app.evidence import retrieve_sentences


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
