"""Retrieve related review mentions. Relevance is never factual entailment."""

import re

from app.query_intent import SOFT_TOPICS, contains, expanded_terms


def retrieve_evidence(business_id, query, intent, reviews, *, limit=2):
    terms = sorted({term for key in intent.soft_topics for term in SOFT_TOPICS[key]}) if intent.soft_topics else expanded_terms(intent)
    ranked = []
    for row in reviews:
        if row.get('business_id') != business_id:
            continue
        text = row['text']
        sentences = [s.strip() for s in re.split(r'(?<=[.!?。！？])\s*', text) if s.strip()]
        choices = [(sum(contains(s, t) for t in terms), i, s) for i, s in enumerate(sentences)]
        if not choices:
            continue
        score, _, excerpt = min(choices, key=lambda x: (-x[0], x[1]))
        if terms and score == 0:
            continue
        ranked.append({'document_id': row['review_id'], 'source': row.get('source', 'yelp_review'),
                       'text': text, 'excerpt': excerpt, 'matched_terms': [t for t in terms if contains(excerpt, t)],
                       'relevance_score': float(score), 'business_id': business_id})
    ranked.sort(key=lambda r: (-r['relevance_score'], r['document_id']))
    # Deduplicate IDs even if an upstream source accidentally repeats a row.
    unique = {row['document_id']: row for row in reversed(ranked)}
    items = sorted(unique.values(), key=lambda r: (-r['relevance_score'], r['document_id']))[:limit]
    return {'status': 'related_mentions' if items and terms else 'not_requested' if not terms else 'insufficient',
            'items': items, 'interpretation': 'lexical relevance only; may contain negative or conflicting statements'}
