"""Compose frozen profile recall, hard constraints and explicit degradation."""

from app.models import EvidenceItem, RecommendationResponse, RestaurantRecommendation
from app.ranking.fusion import fuse_rrf
from app.recommender import recommend_restaurants
from app.serving.model import RequestRecallIndex


RECOVERABLE = (OSError, ValueError, KeyError, TypeError)


class LoadedDataset:
    def __init__(self, businesses, reviews):
        self.businesses, self.reviews = businesses, reviews

    def load_businesses(self):
        return self.businesses

    def load_representative_reviews_by_business(self):
        return self.reviews


def recommend_personalized(request, dataset_repository, serving_repository):
    business_rows = dataset_repository.load_businesses()
    businesses = {row["business_id"]: row for row in business_rows}
    if len(businesses) != len(business_rows):
        raise ValueError("Duplicate online business IDs")
    warnings = []
    try:
        reviews = dataset_repository.load_representative_reviews_by_business()
    except RECOVERABLE:
        reviews = {}
        warnings.append("evidence_unavailable")

    def fallback(reason, *, bundle=None, seen=None):
        rows = business_rows if seen is None else [row for row in business_rows if row["business_id"] not in seen]
        return RecommendationResponse(
            version="v2", engine="processed_rule_fallback",
            recommendations=recommend_restaurants(request, LoadedDataset(rows, reviews)),
            metadata={"profile_found": bundle is not None and request.user_id in bundle["profiles"],
                      "snapshot_cutoff": bundle["manifest"]["snapshot_cutoff"] if bundle else None,
                      "warnings": sorted(set(warnings + [reason])), "query_used_for_ranking": True})

    try:
        bundle = serving_repository.load()
        index = RequestRecallIndex(bundle, businesses, request)
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
    fused = fuse_rrf(channels, weights=config["weights"], k=config["k"], budgets=config["budgets"], allowed=allowed)
    engine = "personalized_weighted_rrf"
    if not profile["positive_business_ids"] or (not fused and allowed):
        if "popularity" not in channels:
            return fallback("all_enabled_channels_unavailable", bundle=bundle, seen=set(profile["seen_business_ids"]))
        fused = fuse_rrf({"popularity": channels["popularity"]}, allowed=allowed)
        engine = "personalized_geo_popularity"
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
            evidence=[EvidenceItem(document_id=row["review_id"], source=row.get("source", "yelp_review"), text=row["text"])
                      for row in reviews.get(item, [])[:2]],
            channel_scores=rec["channel_scores"], reason_business_ids=rec["reason_business_ids"]))
    manifest = bundle["manifest"]
    return RecommendationResponse(
        version="v2", engine=engine, recommendations=results,
        metadata={"profile_found": request.user_id in bundle["profiles"],
                  "model_version": manifest["model_version"], "profile_version": manifest["profile_version"],
                  "snapshot_cutoff": manifest["snapshot_cutoff"], "fusion_config": config["name"],
                  "selection_sha256": manifest["selection_sha256"], "warnings": sorted(set(warnings)),
                  "history_mode": "offline_snapshot", "query_used_for_ranking": False,
                  "is_open_semantics": "dataset_open_flag"})
