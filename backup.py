"""Consistent online SQLite backup. Destination must be in a protected directory."""
import argparse
from pathlib import Path
import sqlite3

if __name__ == '__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('source')
    parser.add_argument('destination')
    args=parser.parse_args()
    source=Path(args.source).resolve(strict=True)
    destination=Path(args.destination).resolve()
    if destination.exists():
        raise SystemExit('El destino ya existe; no se sobrescribe.')
    destination.parent.mkdir(parents=True,exist_ok=True)
    with sqlite3.connect(source.as_uri()+'?mode=ro',uri=True) as src, sqlite3.connect(destination) as dst:
        src.backup(dst)
        # Backups do not preserve live access tokens or staged personal data.
        dst.execute('DELETE FROM imports')
        dst.execute('DELETE FROM sessions')
        dst.commit()
        assert dst.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
    print('Copia verificada. Protege y cifra este archivo: contiene datos personales.')
