"""History-only LambdaRank features, frozen promotion, and safe model loading."""

import hashlib
import json
import math
from pathlib import Path
from threading import Lock

from app.artifact_io import verify_artifacts


FEATURES = ['rrf_score', 'pop_rank', 'cf_rank', 'content_rank', 'cf_score', 'content_score',
            'historical_popularity', 'positive_user_count', 'historical_bayesian_rating',
            'history_count', 'positive_seed_count', 'category_affinity', 'price_affinity']
VERSION = 'ranking_v1'


def feature_row(rec, profile, business, popularity):
    channels = rec.get('channel_scores', {})
    def rank(source):
        return 1 / channels[source]['rank'] if source in channels else 0.
    def raw(source):
        return channels.get(source, {}).get('raw_score', 0.)
    categories = business.get('categories_normalized', [])
    preferences = profile.get('category_preferences', {})
    category = sum(preferences.get(c, 0) for c in categories if c.lower() not in {'restaurants', 'food'})
    denominator = max(1, sum(v for c, v in preferences.items() if c.lower() not in {'restaurants', 'food'}))
    price, mean = business.get('price_level'), profile.get('mean_price_level')
    values = [rec['score'], rank('popularity'), rank('itemcf'), rank('content'), raw('itemcf'), raw('content'),
              popularity.get('score', 0), math.log1p(popularity.get('positive_users', 0)),
              popularity.get('bayesian_rating', 0) or 0, math.log1p(profile['history_count']),
              math.log1p(len(profile['positive_business_ids'])), category / denominator,
              1/(1+abs(price-mean)) if price in (1,2,3,4) and mean is not None else 0]
    if not all(math.isfinite(v) for v in values):
        raise ValueError('Nonfinite ranking features')
    return values


def choose_order(metrics):
    return 'lambdarank' if (metrics['lambdarank']['ndcg@10'] or 0) > (metrics['rrf']['ndcg@10'] or 0) else 'rrf'


def rank_candidates(booster, candidates, profile, businesses, popularity):
    if not candidates:
        return []
    x = [feature_row(r, profile, businesses[r['business_id']], popularity.get(r['business_id'], {})) for r in candidates]
    from lightgbm.basic import LightGBMError
    try:
        scores = booster.predict(x, num_threads=1)
    except LightGBMError as exc:
        raise ValueError('Ranker prediction unavailable') from exc
    if len(scores) != len(candidates) or not all(math.isfinite(float(s)) for s in scores):
        raise ValueError('Invalid ranker predictions')
    # The model can only reorder the exact supplied whitelist.
    return [{**r, 'rrf_score': r['score'], 'ranking_score': float(score)}
            for r, score in sorted(zip(candidates, scores), key=lambda p: (-p[1], -p[0]['score'], p[0]['business_id']))]


class RankingRepository:
    def __init__(self, model_dir):
        self.model_dir = Path(model_dir)
        self._bundle = None
        self._lock = Lock()

    def load(self):
        with self._lock:
            if self._bundle is not None:
                return self._bundle
            try:
                manifest = verify_artifacts(self.model_dir, 'experiment_manifest.json')
            except AttributeError as exc:
                raise ValueError('Malformed ranker manifest') from exc
            if manifest['experiment_id'] != VERSION or manifest['feature_schema'] != FEATURES:
                raise ValueError('Unsupported ranker feature schema')
            selection = json.loads((self.model_dir/'selection.json').read_text(encoding='utf-8'))
            if hashlib.sha256(json.dumps(selection, sort_keys=True).encode()).hexdigest() != manifest['selection_sha256']:
                raise ValueError('Ranker selection mismatch')
            if set(selection) != {'city_preference', 'simulated_geo'} or any(v not in ('rrf','lambdarank') for v in selection.values()):
                raise ValueError('Invalid ranker selection')
            import lightgbm as lgb
            try:
                booster = lgb.Booster(model_file=str(self.model_dir/'model.txt'))
            except lgb.basic.LightGBMError as exc:
                raise ValueError('Ranker model unavailable') from exc
            if booster.num_feature() != len(FEATURES) or booster.feature_name() != FEATURES:
                raise ValueError('Ranker model schema mismatch')
            self._bundle = {'manifest': manifest, 'selection': selection, 'booster': booster}
            return self._bundle

    def rerank(self, candidates, profile, businesses, popularity, *, scenario='simulated_geo', query_active=False, recall_config=None):
        if query_active:
            return candidates, {'active': False, 'reason': 'query_task_not_trained'}
        bundle = self.load()
        if set(bundle['manifest']['catalog_ids']) != set(businesses):
            raise ValueError('Ranker catalog mismatch')
        if recall_config is not None and (recall_config['weights'] != bundle['manifest']['candidate_policy'][scenario]
                or recall_config['k'] != 60 or any(recall_config['budgets'].get(s,100) != 100 for s in ('popularity','itemcf','content'))):
            raise ValueError('Ranker recall configuration mismatch')
        selected = bundle['selection'][scenario]
        meta = {'active': selected == 'lambdarank', 'selection': selected, 'version': VERSION,
                'reason': 'validation_promotion' if selected == 'lambdarank' else 'validation_retained_rrf'}
        if selected == 'rrf':
            return candidates, meta
        return rank_candidates(bundle['booster'], candidates, profile, businesses, popularity), meta
