"""Stateless lexical query channel over the request's eligible merchant set."""

import math

from app.evidence import retrieve_evidence
from app.query_intent import contains, expanded_terms


def recall_query(query, intent, businesses, reviews, allowed, *, limit=100):
    terms = expanded_terms(intent)
    if not terms:
        return []
    docs = {item: (businesses[item]['name'] + ' ' + ' '.join(businesses[item]['categories_normalized'])).lower()
            for item in sorted(allowed)}
    frequency = {term: sum(contains(text, term) for text in docs.values()) for term in terms}
    result = []
    for item, text in docs.items():
        score = sum(math.log1p((len(docs)+1)/(frequency[t]+1)) for t in terms if contains(text, t))
        if intent.soft_topics:
            evidence = retrieve_evidence(item, query, intent, reviews.get(item, []), limit=1)
            score += min(2.0, evidence['items'][0]['relevance_score']) if evidence['items'] else 0
        if score > 0:
            result.append({'business_id': item, 'source': 'query', 'score': score, 'reason_business_ids': []})
    return sorted(result, key=lambda r: (-r['score'], r['business_id']))[:limit]
