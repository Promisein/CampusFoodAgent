"""Shared merchant-scoped evidence; relevance and cue rules are not entailment."""
import math
import re
from collections import Counter

from app.query_intent import SOFT_TOPICS, contains, expanded_terms


def retrieve_sentences(business_id,reviews,intent,*,limit=2,include_text=False):
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
        if include_text:ranked[-1]['text']=row['text']
    ranked.sort(key=lambda r:(-r['score'],r['review_id'],r['excerpt']))
    # Distinct review sources, not two fragments falsely counted as corroboration.
    unique=[];seen=set()
    for row in ranked:
        if row['review_id'] not in seen:unique.append(row);seen.add(row['review_id'])
    return unique[:limit]


def retrieve_evidence(business_id, query, intent, reviews, *, limit=2):
    citations = retrieve_sentences(business_id, reviews, intent, limit=limit, include_text=True)
    terms = sorted({term for key in intent.soft_topics for term in SOFT_TOPICS[key]}) if intent.soft_topics else expanded_terms(intent)
    items = [{'document_id': c['review_id'], 'source': c['source'],
              'text': c['text'], 'business_id': business_id,
              'excerpt': c['excerpt'], 'matched_terms': c['matched_terms'],
              'relevance_score': c['score'], 'cue': c['cue']} for c in citations]
    status = 'related_mentions' if items else 'insufficient' if terms else 'not_requested'
    if {c['cue'] for c in citations} == {'negative_cue', 'mention_only'}:
        status = 'mixed_cues'
    return {'status': status, 'items': items,
            'interpretation': 'related mentions and heuristic cues only; not factual entailment'}


def link_answer_evidence(response):
    """Attach answer-local IDs to the same quotes shown on restaurant cards."""
    answer = response.answer
    if not answer:
        return
    covered = [item['business_id'] for item in answer.get('items', [])]
    selected = {(c['business_id'], c['review_id'], c['excerpt']): c['id']
                for c in answer.get('citations', [])}
    by_id = {rec.business_id: rec for rec in response.recommendations}
    for number, business_id in enumerate(covered, 1):
        rec = by_id[business_id]
        for index, evidence in enumerate(rec.evidence, 1):
            evidence.citation_id = f'b{number}_c{index}'
            evidence.used_in_answer = selected.get((business_id, evidence.document_id, evidence.excerpt)) == evidence.citation_id
    response.metadata['evidence_retriever'] = 'merchant_sentence_bm25_v2'
    response.metadata['answer_evidence_covered_business_ids'] = covered
