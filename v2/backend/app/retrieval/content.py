"""Interpretable category TF-IDF retrieval, not a pretrained semantic model."""

import math
from collections import Counter, defaultdict
from itertools import zip_longest

from app.retrieval.baselines import BaselineIndex, parse_time, validate_interactions


def build_content_index(interactions, businesses, cutoff, *, catalog_policy="historical",
                        neighbor_limit=50, shrinkage=5.0):
    if catalog_policy not in {"historical", "snapshot_catalog"}:
        raise ValueError("Unknown catalog policy")
    if neighbor_limit < 1 or not math.isfinite(shrinkage) or shrinkage < 0:
        raise ValueError("Invalid neighbor settings")
    cutoff = parse_time(cutoff).isoformat(sep=" ")
    rows = validate_interactions(interactions, businesses)
    return ContentIndex([row for row in rows if row["event_time"] < cutoff], businesses,
                        cutoff, neighbor_limit, shrinkage, catalog_policy)


def _categories(business):
    return {category.strip().lower() for category in business.get("categories_normalized", [])
            if category.strip() and category.strip().lower() not in {"restaurants", "food"}}


class ContentIndex(BaselineIndex):
    def __init__(self, history, businesses, cutoff, neighbor_limit, shrinkage, catalog_policy):
        super().__init__(history, businesses, cutoff, neighbor_limit, shrinkage)
        self.catalog_policy = catalog_policy
        self.historical_business_ids = set(self.visible_business_ids)
        if catalog_policy == "snapshot_catalog":
            self.visible_business_ids = set(businesses)
            for item in self.visible_business_ids - self.historical_business_ids:
                self.popularity[item] = {"positive_users": 0, "review_count": 0,
                                         "mean_rating": None, "bayesian_rating": None, "score": 0.0}
            self._pop_order = sorted(self.visible_business_ids,
                                     key=lambda item: (-self.popularity[item]["score"], item))
        categories = {item: _categories(businesses[item]) for item in sorted(self.visible_business_ids)}
        frequency = Counter(category for terms in categories.values() for category in terms)
        self.idf = {term: math.log((1 + len(categories)) / (1 + count)) + 1
                    for term, count in sorted(frequency.items())}
        self.item_vectors, self._postings = {}, defaultdict(list)
        for item, terms in categories.items():
            norm = math.sqrt(sum(self.idf[term] ** 2 for term in sorted(terms)))
            vector = {term: self.idf[term] / norm for term in sorted(terms)} if norm else {}
            self.item_vectors[item] = vector
            for term, weight in vector.items():
                self._postings[term].append((item, weight))
        self._request_key, self._recommendations = None, {}

    def content_model(self):
        return {"cutoff": self.cutoff, "catalog_policy": self.catalog_policy,
                "representation": "unit category TF-IDF; generic Food/Restaurants removed",
                "idf": self.idf, "item_vectors": self.item_vectors}

    def _content_recommendations(self, user_id, allowed, distances, limit):
        profile = self.profile(user_id)
        vector = defaultdict(float)
        seeds = profile["positive_weights"]
        for seed, preference in seeds.items():
            for term, weight in self.item_vectors.get(seed, {}).items():
                vector[term] += preference * weight
        norm = math.sqrt(sum(weight ** 2 for weight in vector.values()))
        if not norm:
            return []
        scores = defaultdict(float)
        for term, weight in sorted(vector.items()):
            for item, item_weight in self._postings[term]:
                if item in allowed:
                    scores[item] += weight / norm * item_weight
        mean_price = profile["mean_price_level"]
        for item in scores:
            price = self.businesses[item].get("price_level")
            if mean_price is not None and price in (1, 2, 3, 4):
                scores[item] /= 1 + abs(price - mean_price)
        result = []
        for item in sorted(scores, key=lambda item: (-scores[item], item))[:limit]:
            terms = set(self.item_vectors[item])
            result.append({"business_id": item, "source": "content", "score": scores[item],
                           "distance_km": distances.get(item),
                           "matched_categories": sorted(terms & vector.keys()),
                           "reason_business_ids": [seed for seed in seeds
                                                   if terms & self.item_vectors.get(seed, {}).keys()]})
        return result

    def recommend(self, user_id, source, *, limit=100, radius_km=None, max_price_level=4):
        if source not in {"popularity", "itemcf", "combined", "content", "combined_content"} or limit < 1:
            raise ValueError("Unknown source or nonpositive limit")
        key = (user_id, limit, radius_km, max_price_level)
        if self._request_key != key:
            self._request_key, self._recommendations = key, {}
        if source in self._recommendations:
            return self._recommendations[source]
        if source in {"popularity", "itemcf", "combined"}:
            result = super().recommend(user_id, source, limit=limit, radius_km=radius_km,
                                       max_price_level=max_price_level)
        elif source == "content":
            allowed, _, distances = self.candidate_pool(user_id, radius_km=radius_km,
                                                        max_price_level=max_price_level)
            result = self._content_recommendations(user_id, allowed, distances, limit)
        else:
            channels = [self.recommend(user_id, channel, limit=limit, radius_km=radius_km,
                                        max_price_level=max_price_level)
                        for channel in ("itemcf", "content", "popularity")]
            result, seen = [], set()
            for batch in zip_longest(*channels):
                for candidate in batch:
                    if candidate is not None and candidate["business_id"] not in seen:
                        seen.add(candidate["business_id"])
                        result.append(candidate)
                        if len(result) == limit:
                            break
                if len(result) == limit:
                    break
        self._recommendations[source] = result
        return result
