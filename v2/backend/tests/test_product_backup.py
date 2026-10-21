import json
import sqlite3

import pytest


def test_online_backup_is_restorable_and_checksums_match(tmp_path):
    from app.product.backup import backup_databases

    sources={}
    for name in ('accounts','agent','events'):
        source=tmp_path/f'{name}.sqlite3'
        with sqlite3.connect(source) as db:
            db.execute('CREATE TABLE marker(value TEXT)')
            db.execute('INSERT INTO marker VALUES (?)',(name,))
        sources[name]=source
    output=tmp_path/'backup'
    manifest=backup_databases(sources,output)
    assert sorted(manifest['databases'])==['accounts','agent','events']
    assert json.loads((output/'manifest.json').read_text(encoding='utf-8'))==manifest
    for name,entry in manifest['databases'].items():
        with sqlite3.connect(output/entry['file']) as restored:
            assert restored.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
            assert restored.execute('SELECT value FROM marker').fetchone()[0]==name
    with pytest.raises(FileExistsError):backup_databases(sources,output)


def test_backup_rejects_missing_source_without_partial_output(tmp_path):
    from app.product.backup import backup_databases

    output=tmp_path/'backup'
    with pytest.raises(FileNotFoundError):
        backup_databases({'accounts':tmp_path/'missing.sqlite3'},output)
    assert not output.exists()
