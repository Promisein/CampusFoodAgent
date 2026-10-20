"""Present-snapshot BM25 and statistical LSA retrieval (no pretrained model).

Representative review text is for present query demos, never historical ranking.
The serialized bundle contains only JSON and numeric NumPy arrays.
"""

import argparse
import hashlib
import json
import re
import tempfile
import zipfile
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np
from scipy import sparse
from sklearn.decomposition import TruncatedSVD
from sklearn.preprocessing import normalize

from app import artifact_io
from app.query_intent import expanded_terms

MODEL_VERSION = 'search_v1'
INPUT_NAMES = ('businesses.jsonl', 'representative_reviews.jsonl', 'data_manifest.json')
ARTIFACT_NAMES = {'vocabulary.json', 'arrays.npz'}


def _tokens(text):
    return re.findall(r'[a-z][a-z0-9]+|[\u4e00-\u9fff]+', text.lower())


def _jsonl(path):
    with path.open(encoding='utf-8') as stream:
        return [json.loads(line) for line in stream if line.strip()]


def _hash_json(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def build_search_index(data_dir, output_dir, dimensions=64):
    """Build a deterministic bundle in a dedicated directory and publish whole."""
    data_dir, output_dir = Path(data_dir).resolve(), Path(output_dir).resolve()
    if not isinstance(dimensions, int) or dimensions < 1:
        raise ValueError('dimensions must be a positive integer')
    if output_dir == data_dir or output_dir in data_dir.parents or data_dir in output_dir.parents:
        raise ValueError('Search output must be separate from source data')
    if output_dir.exists():
        if output_dir.is_symlink() or not output_dir.is_dir():
            raise ValueError('Unsafe output directory')
        previous = artifact_io.verify_artifacts(output_dir, 'manifest.json') if (output_dir / 'manifest.json').is_file() else {}
        if previous.get('model_version') != MODEL_VERSION or {p.name for p in output_dir.iterdir()} != ARTIFACT_NAMES | {'manifest.json'}:
            raise ValueError('Refusing to replace an unrelated directory')
    inputs = {name: artifact_io.file_sha256(data_dir / name) for name in INPUT_NAMES}
    source_manifest = json.loads((data_dir / 'data_manifest.json').read_text(encoding='utf-8'))
    rows = _jsonl(data_dir / 'businesses.jsonl')
    businesses = {row['business_id']: row for row in rows}
    if len(rows) != len(businesses) or not businesses or any(not isinstance(k, str) or not k for k in businesses):
        raise ValueError('Invalid or duplicate business catalog')
    catalog = sorted(businesses)
    reviews = defaultdict(list)
    source_counts = Counter()
    for row in _jsonl(data_dir / 'representative_reviews.jsonl'):
        if row.get('business_id') not in businesses:
            raise ValueError('Review outside catalog')
        if not isinstance(row.get('text'), str):
            raise ValueError('Invalid representative review text')
        reviews[row['business_id']].append(row)
        source_counts[str(row.get('source', 'unspecified'))] += 1
    documents = []
    for item in catalog:
        business = businesses[item]
        text = business.get('name', '') + ' ' + ' '.join(business.get('categories_normalized', []))
        text += ' ' + ' '.join(row['text'] for row in sorted(reviews[item], key=lambda r: (r.get('review_id', ''), r['text'])))
        documents.append(Counter(_tokens(text)))
    vocabulary = sorted({term for document in documents for term in document})
    if not vocabulary:
        raise ValueError('Search corpus has no searchable tokens')
    columns = {term: i for i, term in enumerate(vocabulary)}
    rr, cc, values = [], [], []
    for i, document in enumerate(documents):
        for term, count in sorted(document.items()):
            rr.append(i)
            cc.append(columns[term])
            values.append(float(count))
    counts = sparse.csr_matrix((values, (rr, cc)), shape=(len(catalog), len(vocabulary)), dtype=np.float64)
    frequency = np.asarray((counts > 0).sum(axis=0)).ravel()
    idf = np.log((1 + len(catalog)) / (1 + frequency)) + 1
    tfidf = normalize(counts.multiply(idf).tocsr())
    # sklearn SVD requires at least two vocabulary terms; one term is exact.
    if len(vocabulary) == 1:
        components = np.ones((1, 1), dtype=np.float64)
    else:
        size = min(dimensions, len(catalog), len(vocabulary))
        svd = TruncatedSVD(n_components=size, algorithm='randomized', n_iter=7, random_state=0)
        svd.fit(tfidf)
        components = svd.components_
    vectors = normalize(np.asarray(tfidf @ components.T))
    arrays = {'idf': idf, 'components': components, 'vectors': vectors,
              'counts_data': counts.data, 'counts_indices': counts.indices,
              'counts_indptr': counts.indptr, 'lengths': np.asarray(counts.sum(axis=1)).ravel(),
              'bm25_idf': np.log1p((len(catalog) - frequency + .5) / (frequency + .5))}
    if inputs != {name: artifact_io.file_sha256(data_dir / name) for name in INPUT_NAMES}:
        raise ValueError('Source changed during search build')
    manifest = {'model_version': MODEL_VERSION, 'representation': 'BM25 + TF-IDF/SVD LSA; not pretrained',
                'dimensions': components.shape[0], 'requested_dimensions': dimensions,
                'catalog_ids': catalog, 'catalog_sha256': _hash_json(catalog),
                'vocabulary_size': len(vocabulary), 'inputs': inputs,
                'source_data_version': source_manifest.get('data_version'),
                'review_sources': dict(sorted(source_counts.items())),
                'review_count': sum(source_counts.values()), 'usage': 'present_query_only',
                'code_sha256': artifact_io.file_sha256(Path(__file__)),
                'query_code_sha256': artifact_io.file_sha256(Path(__file__).parents[1] / 'query_intent.py'),
                'config': {'bm25_k1': 1.2, 'bm25_b': .75, 'rrf_k': 60, 'random_state': 0}}
    output_dir.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=f'.{output_dir.name}.stage-', dir=output_dir.parent) as temporary:
        stage = Path(temporary)
        (stage / 'vocabulary.json').write_text(json.dumps(vocabulary, ensure_ascii=False) + '\n', encoding='utf-8')
        np.savez_compressed(stage / 'arrays.npz', **arrays)
        artifact_io.publish_directory(stage, output_dir, manifest, 'manifest.json')
    return manifest


class SearchRepository:
    def __init__(self, model_dir):
        self.model_dir = Path(model_dir)
        self._bundle = None

    def load(self):
        if self._bundle is not None:
            return self._bundle
        try:
            manifest = artifact_io.verify_artifacts(self.model_dir, 'manifest.json')
            if manifest['model_version'] != MODEL_VERSION or set(manifest['outputs']) != ARTIFACT_NAMES:
                raise ValueError('Invalid search version or output catalog')
            catalog = manifest['catalog_ids']
            vocabulary = json.loads((self.model_dir / 'vocabulary.json').read_text(encoding='utf-8'))
            if (not catalog or not vocabulary or any(not isinstance(t, str) or not t for t in catalog + vocabulary)
                    or catalog != sorted(set(catalog)) or vocabulary != sorted(set(vocabulary))
                    or _hash_json(catalog) != manifest['catalog_sha256']
                    or set(manifest['inputs']) != set(INPUT_NAMES)):
                raise ValueError('Invalid search catalog or vocabulary')
            for digest in [*manifest['inputs'].values(), manifest['code_sha256'], manifest['query_code_sha256']]:
                if not isinstance(digest, str) or not re.fullmatch('[0-9a-f]{64}', digest):
                    raise ValueError('Invalid provenance hash')
            with np.load(self.model_dir / 'arrays.npz', allow_pickle=False) as source:
                arrays = {name: source[name] for name in source.files}
            n, v, d = len(catalog), len(vocabulary), manifest['dimensions']
            shapes = {'idf': (v,), 'bm25_idf': (v,), 'lengths': (n,),
                      'components': (d, v), 'vectors': (n, d), 'counts_indptr': (n + 1,)}
            if not isinstance(d, int) or not 1 <= d <= min(n, v) or manifest['vocabulary_size'] != v:
                raise ValueError('Invalid search dimensions')
            if set(arrays) != set(shapes) | {'counts_data', 'counts_indices'}:
                raise ValueError('Missing search arrays')
            for name, array in arrays.items():
                if array.dtype.kind not in 'fiu' or not np.isfinite(array).all() or (name in shapes and array.shape != shapes[name]):
                    raise ValueError('Invalid search array: ' + name)
            values, indices, indptr = arrays['counts_data'], arrays['counts_indices'], arrays['counts_indptr']
            if (values.ndim != 1 or indices.shape != values.shape or indices.dtype.kind not in 'iu'
                    or indptr.dtype.kind not in 'iu' or indptr[0] != 0 or indptr[-1] != len(values)
                    or (np.diff(indptr) < 0).any() or (indices < 0).any() or (indices >= v).any()
                    or (values <= 0).any() or (arrays['idf'] <= 0).any() or (arrays['bm25_idf'] < 0).any()):
                raise ValueError('Invalid search sparse matrix')
            counts = sparse.csr_matrix((values, indices, indptr), shape=(n, v))
            if not counts.has_canonical_format or not np.array_equal(np.asarray(counts.sum(axis=1)).ravel(), arrays['lengths']):
                raise ValueError('Invalid search lengths')
            self._bundle = {'manifest': manifest, 'vocabulary': {t: i for i, t in enumerate(vocabulary)},
                            'counts': counts, **arrays}
        except (KeyError, TypeError, AttributeError, IndexError, OverflowError, EOFError, zipfile.BadZipFile) as exc:
            raise ValueError('Malformed search bundle') from exc
        return self._bundle

    def recommend(self, query, intent, businesses, allowed, limit=100):
        if not isinstance(limit, int) or limit < 1:
            raise ValueError('limit must be positive')
        if not intent.has_query_signal:
            return []
        bundle = self.load()
        catalog = bundle['manifest']['catalog_ids']
        if set(catalog) != set(businesses):
            raise ValueError('Search catalog differs from serving catalog')
        terms = Counter(token for term in expanded_terms(intent) for token in _tokens(term))
        query_columns = {bundle['vocabulary'][term]: count for term, count in terms.items() if term in bundle['vocabulary']}
        if not query_columns:
            return []
        # Both channels operate only on eligible rows, before any top-k budget.
        rows = np.asarray([i for i, item in enumerate(catalog) if item in allowed], dtype=np.int64)
        if not len(rows):
            return []
        counts = bundle['counts'][rows]
        lengths = bundle['lengths'][rows]
        average = float(np.mean(bundle['lengths']))
        lexical = np.zeros(len(rows))
        for column in sorted(query_columns):
            tf = counts[:, column].toarray().ravel()
            lexical += bundle['bm25_idf'][column] * (tf * 2.2) / (tf + 1.2 * (.25 + .75 * lengths / max(average, 1e-12)))
        query_vector = np.zeros(len(bundle['vocabulary']))
        for column, count in query_columns.items():
            query_vector[column] = count * bundle['idf'][column]
        latent = query_vector @ bundle['components'].T
        norm = np.linalg.norm(latent)
        semantic = bundle['vectors'][rows] @ (latent / norm) if norm > 1e-12 else np.zeros(len(rows))
        scores = defaultdict(float)
        for channel in (lexical, semantic):
            order = sorted((j for j, score in enumerate(channel) if score > 1e-12), key=lambda j: (-float(channel[j]), catalog[rows[j]]))[:limit]
            for rank, j in enumerate(order, 1):
                scores[catalog[rows[j]]] += 1 / (60 + rank)
        return [{'business_id': item, 'score': scores[item], 'source': 'semantic', 'reason_business_ids': []}
                for item in sorted(scores, key=lambda item: (-scores[item], item))[:limit]]


def main():
    backend = Path(__file__).resolve().parents[2]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data-dir', type=Path, default=backend / 'data' / 'processed')
    parser.add_argument('--output-dir', type=Path, default=backend / 'data' / 'derived' / MODEL_VERSION)
    parser.add_argument('--dimensions', type=int, default=64)
    args = parser.parse_args()
    manifest = build_search_index(args.data_dir, args.output_dir, args.dimensions)
    print(json.dumps({'model_version': MODEL_VERSION, 'business_count': len(manifest['catalog_ids']),
                      'dimensions': manifest['dimensions'], 'outputs': manifest['outputs']}, sort_keys=True))


if __name__ == '__main__':
    main()
