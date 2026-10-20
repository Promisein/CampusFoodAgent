"""Compose frozen profile recall, hard constraints and explicit degradation."""

from app.models import EvidenceItem, RecommendationResponse, RestaurantRecommendation
from app.ranking.fusion import fuse_rrf
from app.recommender import recommend_restaurants
from app.serving.model import RequestRecallIndex
from app.query_intent import parse_intent, resolve_request, matches_categories
from app.retrieval.query import recall_query
from app.evidence import retrieve_evidence


RECOVERABLE = (OSError, ValueError, KeyError, TypeError)


class LoadedDataset:
    def __init__(self, businesses, reviews):
        self.businesses, self.reviews = businesses, reviews

    def load_businesses(self):
        return self.businesses

    def load_representative_reviews_by_business(self):
        return self.reviews


def query_metadata(request, intent):
    return {"intent": intent.to_dict(), "pipeline_version": "query_v1",
            "resolved_constraints": {"radius_km": request.radius_km, "max_price_level": request.max_price_level,
                                     "city": request.city},
            "evidence_interpretation": "related mentions only; not positive factual support",
            "is_open_semantics": "dataset_open_flag"}


def attach_evidence(recommendations, request, intent, reviews):
    for rec in recommendations:
        evidence = retrieve_evidence(rec.business_id, request.query, intent, reviews.get(rec.business_id, []))
        rec.evidence = [EvidenceItem(**item) for item in evidence['items']]
        rec.evidence_status = evidence['status']
        if intent.soft_topics:
            rec.reasons.append("Related review mentions; verify the quoted context" if rec.evidence else "Insufficient review evidence for requested soft preferences")
    return recommendations


def query_channel(request, intent, businesses, reviews, allowed, warnings):
    try:
        return recall_query(request.query, intent, businesses, reviews, allowed)
    except RECOVERABLE:
        warnings.append('query_unavailable')
        return []


def recommend_anonymous(request, dataset_repository):
    intent = parse_intent(request.query)
    request = resolve_request(request, intent)
    metadata = query_metadata(request, intent)
    if intent.needs_clarification:
        return RecommendationResponse(version="v2", engine="query_needs_clarification", recommendations=[],
                                      metadata={**metadata, "warnings": intent.unresolved_constraints, "query_used_for_ranking": False})
    rows = [b for b in dataset_repository.load_businesses() if matches_categories(b, intent)]
    warnings = []
    try:
        reviews = dataset_repository.load_representative_reviews_by_business()
    except RECOVERABLE:
        reviews = {}
        warnings.append("evidence_unavailable")
    # Rules score all eligible merchants; query retrieval is not restricted by its top20.
    all_rules = recommend_restaurants(request.model_copy(update={"top_k": max(1, len(rows))}), LoadedDataset(rows, reviews))
    by_id = {rec.business_id: rec for rec in all_rules}
    channels = {"rule": [{"business_id": r.business_id, "score": r.score} for r in all_rules[:100]]}
    query_rows = query_channel(request, intent, {b['business_id']: b for b in rows}, reviews, set(by_id), warnings)
    if query_rows:
        channels['query'] = query_rows
        fused = fuse_rrf(channels, weights={"rule": 1, "query": 2}, allowed=set(by_id))
        recs = []
        for row in fused[:request.top_k]:
            rec = by_id[row['business_id']].model_copy(update={"score": row['score'], "channel_scores": row['channel_scores']})
            recs.append(rec)
    else:
        recs = all_rules[:request.top_k]
    if intent.has_query_signal and not query_rows:
        warnings.append("query_no_lexical_match")
    return RecommendationResponse(version="v2", engine="processed_geo_keyword_evidence",
                                  recommendations=attach_evidence(recs, request, intent, reviews),
                                  metadata={**metadata, "warnings": warnings, "query_used_for_ranking": intent.has_query_signal})


def recommend_personalized(request, dataset_repository, serving_repository):
    intent = parse_intent(request.query)
    request = resolve_request(request, intent)
    query_meta = query_metadata(request, intent)
    if intent.needs_clarification:
        return RecommendationResponse(version="v2", engine="query_needs_clarification", recommendations=[],
                                      metadata={**query_meta, "warnings": intent.unresolved_constraints, "query_used_for_ranking": False})
    business_rows = dataset_repository.load_businesses()
    businesses = {row["business_id"]: row for row in business_rows}
    if len(businesses) != len(business_rows):
        raise ValueError("Duplicate online business IDs")
    warnings = []
    eligible_ids = {item for item, business in businesses.items() if matches_categories(business, intent)}
    try:
        reviews = dataset_repository.load_representative_reviews_by_business()
    except RECOVERABLE:
        reviews = {}
        warnings.append("evidence_unavailable")

    def fallback(reason, *, bundle=None, seen=None):
        rows = [row for row in business_rows if row['business_id'] in eligible_ids and (seen is None or row['business_id'] not in seen)]
        response = recommend_anonymous(request, LoadedDataset(rows, reviews))
        return RecommendationResponse(
            version="v2", engine="processed_rule_fallback",
            recommendations=response.recommendations,
            metadata={**response.metadata, "profile_found": bundle is not None and request.user_id in bundle["profiles"],
                      "snapshot_cutoff": bundle["manifest"]["snapshot_cutoff"] if bundle else None,
                      "warnings": sorted(set(warnings + response.metadata['warnings'] + [reason])),
                      "query_used_for_ranking": response.metadata['query_used_for_ranking']})

    try:
        bundle = serving_repository.load()
        index = RequestRecallIndex(bundle, businesses, request, allowed_ids=eligible_ids)
    except RECOVERABLE:
        return fallback("model_unavailable")
    profile = index.profile(request.user_id)
    config = bundle["manifest"]["selection"]["simulated_geo"]
    allowed, _, distances = index.candidate_pool(request.user_id)
    channels = {}
    for name in ("popularity", "itemcf", "content"):
        if name in bundle["disabled_channels"]:
            warnings.append(f"{name}_unavailable")
            continue
        try:
            channels[name] = index.recommend(request.user_id, name)
        except RECOVERABLE:
            warnings.append(f"{name}_unavailable")
    query_rows = query_channel(request, intent, businesses, reviews, allowed, warnings)
    weights, budgets = dict(config['weights']), dict(config['budgets'])
    if query_rows:
        channels['query'] = query_rows
        weights['query'], budgets['query'] = 2, 100
    elif intent.has_query_signal:
        warnings.append('query_no_lexical_match')
    fused = fuse_rrf(channels, weights=weights, k=config["k"], budgets=budgets, allowed=allowed)
    engine = "personalized_weighted_rrf"
    if (not profile["positive_business_ids"] and not query_rows) or (not fused and allowed):
        if "popularity" not in channels:
            return fallback("all_enabled_channels_unavailable", bundle=bundle, seen=set(profile["seen_business_ids"]))
        fused = fuse_rrf({"popularity": channels["popularity"]}, allowed=allowed)
        engine = "personalized_geo_popularity"
    elif query_rows:
        engine = "personalized_query_rrf"
    results = []
    for rec in fused[:request.top_k]:
        item = rec["business_id"]
        if item not in allowed:
            raise ValueError("Fused result escaped the hard-filter whitelist")
        business = businesses[item]
        results.append(RestaurantRecommendation(
            business_id=item, name=business["name"], city=business["city"],
            categories=business["categories_normalized"], price_level=business["price_level"],
            rating=business["stars"], review_count=business["review_count"],
            distance_km=distances[item], score=rec["score"],
            reasons=[f"{distances[item]:.1f} km from requested location",
                     "recall sources: " + ", ".join(rec["channel_scores"])],
            evidence=[],
            channel_scores=rec["channel_scores"], reason_business_ids=rec["reason_business_ids"]))
    manifest = bundle["manifest"]
    return RecommendationResponse(
        version="v2", engine=engine, recommendations=attach_evidence(results, request, intent, reviews),
        metadata={**query_meta, "profile_found": request.user_id in bundle["profiles"],
                  "model_version": manifest["model_version"], "profile_version": manifest["profile_version"],
                  "snapshot_cutoff": manifest["snapshot_cutoff"], "fusion_config": config["name"],
                  "selection_sha256": manifest["selection_sha256"], "warnings": sorted(set(warnings)),
                  "history_mode": "offline_snapshot", "query_used_for_ranking": intent.has_query_signal,
                  "query_fusion": {"weight": 2, "k": config['k'], "budget": 100} if query_rows else None,
                  "is_open_semantics": "dataset_open_flag"})
