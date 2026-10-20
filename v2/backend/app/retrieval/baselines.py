"""CPU-only baselines. Business snapshot popularity/open status is never a feature."""

import math
from collections import Counter, defaultdict
from datetime import datetime
from itertools import combinations, zip_longest


def parse_time(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Invalid event time: {value!r}") from exc
    if parsed.tzinfo is not None:
        raise ValueError("Use the dataset's consistent naive timestamps; timezone conversion is not inferred")
    return parsed


def validate_interactions(rows: list[dict], businesses: dict[str, dict]) -> list[dict]:
    seen = set()
    validated = []
    for row in rows:
        for key in ("interaction_id", "user_id", "business_id"):
            if not isinstance(row.get(key), str) or not row[key].strip():
                raise ValueError(f"Missing or invalid {key}")
        if row["interaction_id"] in seen:
            raise ValueError(f"Duplicate interaction_id: {row['interaction_id']}")
        seen.add(row["interaction_id"])
        if row["business_id"] not in businesses:
            raise ValueError(f"Unknown business_id: {row['business_id']}")
        try:
            rating = float(row["rating"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("Missing or invalid rating") from exc
        if isinstance(row["rating"], bool) or not math.isfinite(rating) or not 1 <= rating <= 5:
            raise ValueError("Rating must be finite and between 1 and 5")
        # Keep only fields needed by the experiment, not review text.
        validated.append({
            "interaction_id": row["interaction_id"], "user_id": row["user_id"],
            "business_id": row["business_id"], "rating": rating,
            "event_time": parse_time(row.get("event_time")).isoformat(sep=" "),
        })
    return sorted(validated, key=lambda row: (row["event_time"], row["interaction_id"]))


def distance_km(lat1, lon1, lat2, lon2):
    lat1, lat2 = math.radians(lat1), math.radians(lat2)
    dlat, dlon = lat2 - lat1, math.radians(lon2 - lon1)
    a = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 6371.0088 * 2 * math.asin(math.sqrt(min(1.0, a)))


def _coordinates(business):
    try:
        lat, lon = float(business["latitude"]), float(business["longitude"])
    except (KeyError, TypeError, ValueError):
        return None
    return (lat, lon) if math.isfinite(lat) and math.isfinite(lon) and -90 <= lat <= 90 and -180 <= lon <= 180 else None


def build_index(interactions, businesses, cutoff, *, neighbor_limit=50, shrinkage=5.0):
    if neighbor_limit < 1 or not math.isfinite(shrinkage) or shrinkage < 0:
        raise ValueError("neighbor_limit must be positive and shrinkage finite/nonnegative")
    cutoff = parse_time(cutoff).isoformat(sep=" ")
    rows = validate_interactions(interactions, businesses)
    return BaselineIndex([row for row in rows if row["event_time"] < cutoff],
                         businesses, cutoff, neighbor_limit, shrinkage)


class BaselineIndex:
    def __init__(self, history, businesses, cutoff, neighbor_limit, shrinkage):
        self.businesses, self.cutoff = businesses, cutoff
        self.history = history
        self.visible_business_ids = {row["business_id"] for row in history}
        self._histories = defaultdict(list)
        item_ratings = defaultdict(list)
        for row in history:
            self._histories[row["user_id"]].append(row)
            item_ratings[row["business_id"]].append(row["rating"])
        self.profiles = {user: self._make_profile(user, rows)
                         for user, rows in sorted(self._histories.items())}
        self._seen = {user: set(profile["seen_business_ids"])
                      for user, profile in self.profiles.items()}
        positive_users = Counter()
        cooccurrence = Counter()
        for profile in self.profiles.values():
            items = profile["positive_business_ids"]
            positive_users.update(items)
            cooccurrence.update(combinations(items, 2))
        self.neighbors = defaultdict(list)
        for (left, right), support in sorted(cooccurrence.items()):
            similarity = support / math.sqrt(positive_users[left] * positive_users[right])
            similarity *= support / (support + shrinkage)
            for item, other in ((left, right), (right, left)):
                self.neighbors[item].append({"business_id": other,
                                             "similarity": similarity, "support": support})
        for item in self.neighbors:
            self.neighbors[item] = sorted(self.neighbors[item],
                                          key=lambda row: (-row["similarity"], row["business_id"]))[:neighbor_limit]
        global_mean = sum(row["rating"] for row in history) / len(history) if history else 3.0
        self.popularity = {}
        for item, ratings in sorted(item_ratings.items()):
            bayesian = (sum(ratings) + 5 * global_mean) / (len(ratings) + 5)
            self.popularity[item] = {
                "positive_users": positive_users[item], "review_count": len(ratings),
                "mean_rating": sum(ratings) / len(ratings), "bayesian_rating": bayesian,
                "score": math.log1p(positive_users[item]) * bayesian / 5,
            }
        self._pop_order = sorted(self.visible_business_ids,
                                 key=lambda item: (-self.popularity[item]["score"], item))
        self._last_pool_key, self._last_pool = None, None

    def _make_profile(self, user, rows):
        latest = {row["business_id"]: row for row in rows}
        positive = {item: row["rating"] - 3 for item, row in latest.items() if row["rating"] >= 4}
        categories = Counter()
        for item, weight in positive.items():
            for category in self.businesses[item].get("categories_normalized", []):
                categories[category] += weight
        coords = [_coordinates(self.businesses[row["business_id"]]) for row in rows]
        coords = [coord for coord in coords if coord is not None]
        prices = [self.businesses[row["business_id"]].get("price_level") for row in rows]
        prices = [price for price in prices if price in (1, 2, 3, 4)]
        return {
            "user_id": user, "as_of_time": self.cutoff, "history_count": len(rows),
            "history_end_time": rows[-1]["event_time"] if rows else None,
            "cohort": "cold" if not rows else "light" if len(rows) < 5 else "warm",
            "seen_business_ids": sorted(latest), "positive_business_ids": sorted(positive),
            "positive_weights": dict(sorted(positive.items())),
            "category_preferences": dict(sorted(categories.items())),
            "mean_price_level": sum(prices) / len(prices) if prices else None,
            "geo_center": [sum(c[0] for c in coords) / len(coords),
                           sum(c[1] for c in coords) / len(coords)] if coords else None,
        }

    def profile(self, user_id):
        return self.profiles.get(user_id) or self._make_profile(user_id, [])

    def candidate_pool(self, user_id, *, radius_km=None, max_price_level=4):
        if radius_km is not None and (not math.isfinite(radius_km) or radius_km <= 0):
            raise ValueError("radius_km must be positive and finite")
        if max_price_level not in (1, 2, 3, 4):
            raise ValueError("max_price_level must be 1..4")
        key = (user_id, radius_km, max_price_level)
        if key == self._last_pool_key:
            return self._last_pool
        seen = self._seen.get(user_id, set())
        center = self.profile(user_id)["geo_center"]
        distances = {}
        if radius_km is None:
            allowed = self.visible_business_ids - seen
            order = [item for item in self._pop_order if item in allowed]
        else:
            allowed = set()
            if center is not None:
                for item in sorted(self.visible_business_ids - seen):
                    business = self.businesses[item]
                    price, coord = business.get("price_level"), _coordinates(business)
                    if price not in (1, 2, 3, 4) or price > max_price_level or coord is None:
                        continue
                    distance = distance_km(*center, *coord)
                    if distance <= radius_km:
                        allowed.add(item)
                        distances[item] = distance
            order = sorted(allowed, key=lambda item: (
                -self.popularity[item]["score"] / (1 + distances[item]), item))
        pool = (allowed, order, distances)
        # Only the current request is cached, keeping a full replay memory-bounded.
        self._last_pool_key, self._last_pool = key, pool
        return pool

    def recommend(self, user_id, source, *, limit=100, radius_km=None, max_price_level=4):
        if source not in {"popularity", "itemcf", "combined"} or limit < 1:
            raise ValueError("Unknown source or nonpositive candidate limit")
        allowed, popular, distances = self.candidate_pool(
            user_id, radius_km=radius_km, max_price_level=max_price_level)
        pop_recs = [{"business_id": item, "source": "popularity",
                     "score": self.popularity[item]["score"] / (1 + distances.get(item, 0)),
                     "distance_km": distances.get(item), "reason_business_ids": []}
                    for item in popular[:limit]]
        if source == "popularity":
            return pop_recs
        scores, reasons = defaultdict(float), defaultdict(list)
        for seed, weight in self.profile(user_id)["positive_weights"].items():
            for neighbor in self.neighbors.get(seed, []):
                item = neighbor["business_id"]
                if item in allowed:
                    scores[item] += weight * neighbor["similarity"]
                    reasons[item].append(seed)
        cf_recs = [{"business_id": item, "source": "itemcf", "score": scores[item],
                    "distance_km": distances.get(item), "reason_business_ids": reasons[item]}
                   for item in sorted(scores, key=lambda item: (-scores[item], item))[:limit]]
        if source == "itemcf":
            return cf_recs
        result, emitted = [], set()
        for pair in zip_longest(cf_recs, pop_recs):
            for candidate in pair:
                if candidate is not None and candidate["business_id"] not in emitted:
                    emitted.add(candidate["business_id"])
                    result.append(candidate)
                    if len(result) == limit:
                        return result
        return result
