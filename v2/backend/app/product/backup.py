"""Consistent per-database online SQLite backups for the local product preview."""
import argparse
from contextlib import closing
from datetime import datetime,timezone
import hashlib
import json
from pathlib import Path
import re
import sqlite3
from tempfile import TemporaryDirectory


ROOT=Path(__file__).resolve().parents[2]
DATABASES={
    'accounts':ROOT/'data/derived/product_v1/accounts.sqlite3',
    'agent':ROOT/'data/derived/agent_v1/sessions.sqlite3',
    'events':ROOT/'data/derived/demo_events/events.sqlite3',
}


def backup_databases(sources,output_dir):
    output=Path(output_dir).resolve()
    if output.exists():raise FileExistsError(output)
    normalized={}
    for name,source in sources.items():
        if not re.fullmatch(r'[a-z0-9_-]+',name):raise ValueError('Invalid database name')
        source=Path(source).resolve()
        if not source.is_file():raise FileNotFoundError(source)
        normalized[name]=source
    output.parent.mkdir(parents=True,exist_ok=True)
    with TemporaryDirectory(prefix='.product-backup-',dir=output.parent) as temporary:
        stage=Path(temporary)
        manifest={'version':'product_backup_v1','created_at':datetime.now(timezone.utc).isoformat(),
                  'consistency':'Each SQLite database is backed up atomically; the three files are not one cross-database snapshot.',
                  'databases':{}}
        for name,source in sorted(normalized.items()):
            filename=f'{name}.sqlite3'
            destination=stage/filename
            with closing(sqlite3.connect(source.as_uri()+'?mode=ro',uri=True)) as original:
                with closing(sqlite3.connect(destination)) as copy:
                    original.backup(copy)
                    if copy.execute('PRAGMA integrity_check').fetchone()[0]!='ok':
                        raise OSError(f'Backup integrity check failed: {name}')
            manifest['databases'][name]={'file':filename,
                'sha256':hashlib.sha256(destination.read_bytes()).hexdigest(),
                'bytes':destination.stat().st_size}
        (stage/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        stage.rename(output)
    return manifest


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir',type=Path,required=True)
    args=parser.parse_args(argv)
    result=backup_databases(DATABASES,args.output_dir)
    print(json.dumps({'output_dir':str(args.output_dir.resolve()),'databases':sorted(result['databases'])},ensure_ascii=False))
    return 0


if __name__=='__main__':raise SystemExit(main())
