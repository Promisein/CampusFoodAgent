import json

import pytest


def fixture_data(tmp_path):
    data = tmp_path / 'processed'
    data.mkdir()
    businesses = {
        'a': {'business_id': 'a', 'name': 'Quiet Coffee', 'categories_normalized': ['Coffee']},
        'b': {'business_id': 'b', 'name': 'Pizza Patio', 'categories_normalized': ['Pizza']},
        'c': {'business_id': 'c', 'name': 'Coffee House', 'categories_normalized': ['Coffee']},
    }
    (data / 'businesses.jsonl').write_text('\n'.join(json.dumps(v) for v in businesses.values()), encoding='utf-8')
    (data / 'representative_reviews.jsonl').write_text(json.dumps({'business_id': 'a', 'review_id': 'r1', 'text': 'peaceful conversation coffee', 'source': 'yelp'}), encoding='utf-8')
    (data / 'data_manifest.json').write_text(json.dumps({'data_version': 'fixture'}), encoding='utf-8')
    return data, businesses


def test_build_load_query_deterministic_whitelist_and_metadata(tmp_path):
    from app.retrieval.semantic import SearchRepository, build_search_index
    from app.query_intent import parse_intent
    data, businesses = fixture_data(tmp_path)
    first, second = tmp_path / 'index1', tmp_path / 'index2'
    manifest = build_search_index(data, first, dimensions=2)
    other = build_search_index(data, second, dimensions=2)
    assert manifest == other
    assert manifest['representation'] == 'BM25 + TF-IDF/SVD LSA; not pretrained'
    assert manifest['catalog_ids'] == sorted(businesses)
    assert set(manifest['inputs']) == {'businesses.jsonl', 'representative_reviews.jsonl', 'data_manifest.json'}
    assert manifest['code_sha256']
    repo = SearchRepository(first)
    assert repo.load() is repo.load()
    query = '咖啡'
    result = repo.recommend(query, parse_intent(query), businesses, {'c'}, limit=1)
    assert [row['business_id'] for row in result] == ['c']
    assert result[0]['source'] == 'semantic'
    assert result[0]['reason_business_ids'] == []
    assert result[0]['score'] > 0
    assert result == SearchRepository(second).recommend(query, parse_intent(query), businesses, {'c'}, limit=1)
    assert repo.recommend('', parse_intent(''), businesses, set(businesses)) == []
    assert repo.recommend('zxywuv', parse_intent('zxywuv'), businesses, set(businesses)) == []
    assert repo.recommend('peaceful', parse_intent('peaceful'), businesses, {'a'}, limit=1)[0]['business_id'] == 'a'
    assert repo.recommend(query, parse_intent(query), businesses, set()) == []
    with pytest.raises(ValueError, match='catalog'):
        repo.recommend(query, parse_intent(query), {'a': businesses['a']}, {'a'})


def test_index_integrity_and_no_overwrite_of_unrelated_directory(tmp_path):
    from app.retrieval.semantic import SearchRepository, build_search_index
    data, _ = fixture_data(tmp_path)
    output = tmp_path / 'index'
    build_search_index(data, output, dimensions=2)
    (output / 'arrays.npz').write_bytes(b'bad')
    with pytest.raises((ValueError, OSError)):
        SearchRepository(output).load()
    with pytest.raises(ValueError):
        build_search_index(data, data)
    unrelated = tmp_path / 'unrelated'
    unrelated.mkdir()
    (unrelated / 'keep.txt').write_text('keep')
    with pytest.raises(ValueError):
        build_search_index(data, unrelated)
    assert (unrelated / 'keep.txt').read_text() == 'keep'


def test_empty_document_catalog_and_corrupt_array_validation(tmp_path):
    from app import artifact_io
    from app.retrieval.semantic import SearchRepository, build_search_index
    import numpy as np
    data, _ = fixture_data(tmp_path)
    output = tmp_path / 'index'
    build_search_index(data, output, dimensions=2)
    with np.load(output / 'arrays.npz', allow_pickle=False) as source:
        arrays = {k: source[k] for k in source.files}
    arrays['idf'][0] = np.nan
    np.savez_compressed(output / 'arrays.npz', **arrays)
    manifest = json.loads((output / 'manifest.json').read_text())
    manifest['outputs']['arrays.npz'] = {'sha256': artifact_io.file_sha256(output / 'arrays.npz'), 'bytes': (output / 'arrays.npz').stat().st_size}
    (output / 'manifest.json').write_text(json.dumps(manifest))
    with pytest.raises(ValueError):
        SearchRepository(output).load()


def test_manifest_provenance_and_invalid_input(tmp_path):
    from app.retrieval.semantic import build_search_index
    data, _ = fixture_data(tmp_path)
    with (data / 'representative_reviews.jsonl').open('a') as stream:
        stream.write('\n' + json.dumps({'business_id': 'unknown', 'text': 'coffee'}))
    with pytest.raises(ValueError, match='catalog'):
        build_search_index(data, tmp_path / 'index')


@pytest.mark.parametrize('mutation', ['dimensions', 'vocabulary', 'catalog', 'inputs'])
def test_valid_hashes_do_not_bypass_bundle_schema_validation(tmp_path, mutation):
    from app.retrieval.semantic import SearchRepository, build_search_index
    data, _ = fixture_data(tmp_path)
    output = tmp_path / 'index'
    manifest = build_search_index(data, output, dimensions=2)
    if mutation == 'dimensions':
        manifest['dimensions'] = 999
    elif mutation == 'vocabulary':
        manifest['vocabulary_size'] += 1
    elif mutation == 'catalog':
        manifest['catalog_ids'] = ['a']
    else:
        manifest['inputs']['businesses.jsonl'] = 'invalid-hash'
    (output / 'manifest.json').write_text(json.dumps(manifest), encoding='utf-8')
    with pytest.raises(ValueError):
        SearchRepository(output).load()


def test_malformed_zip_raises_public_error_type(tmp_path):
    from app import artifact_io
    from app.retrieval.semantic import SearchRepository, build_search_index
    data, _ = fixture_data(tmp_path)
    output = tmp_path / 'index'
    manifest = build_search_index(data, output, dimensions=2)
    (output / 'arrays.npz').write_bytes(b'PK\x03\x04malformed zip')
    manifest['outputs']['arrays.npz'] = {'sha256': artifact_io.file_sha256(output / 'arrays.npz'), 'bytes': (output / 'arrays.npz').stat().st_size}
    (output / 'manifest.json').write_text(json.dumps(manifest), encoding='utf-8')
    with pytest.raises((ValueError, OSError)):
        SearchRepository(output).load()


def test_non_mapping_manifest_is_recoverable(tmp_path):
    from app.retrieval.semantic import SearchRepository
    (tmp_path / 'manifest.json').write_text('[]', encoding='utf-8')
    with pytest.raises((ValueError, OSError)):
        SearchRepository(tmp_path).load()
