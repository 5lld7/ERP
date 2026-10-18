"""Consistent SQLite backups, including uploaded employee documents."""
import argparse
import logging
import os
import re
import secrets
import sqlite3
import threading
import time
from pathlib import Path

import erp


def create_backup(directory=None,retain=14):
    directory=Path(directory or erp.DATA/'backups')
    directory.mkdir(parents=True,exist_ok=True)
    filename='erp-auto-'+time.strftime('%Y%m%d-%H%M%S')+'-'+secrets.token_hex(3)+'.sqlite3'
    path=directory/filename
    source=erp.connect()
    dest=sqlite3.connect(path)
    try:
        source.backup(dest)
        if dest.execute('PRAGMA quick_check').fetchone()[0]!='ok':
            raise RuntimeError('Backup integrity check failed')
    finally:
        dest.close()
        source.close()
    # Only rotate files produced by this worker; never remove manual backups.
    files=sorted((p for p in directory.iterdir() if re.fullmatch(r'erp-auto-\d{8}-\d{6}-[0-9a-f]{6}\.sqlite3',p.name)),key=lambda p:p.stat().st_mtime,reverse=True)
    for old in files[max(1,retain):]:
        old.unlink()
    return path


def start_worker(stop):
    hours=float(os.environ.get('ERP_BACKUP_INTERVAL_HOURS','24'))
    retain=int(os.environ.get('ERP_BACKUP_RETENTION','14'))
    if hours<=0:
        return None
    def worker():
        while not stop.is_set():
            try:
                create_backup(retain=retain)
                logging.getLogger('erp').info('Automatic database backup completed')
                delay=hours*3600
            except Exception:
                logging.getLogger('erp').exception('Automatic backup failed')
                delay=min(hours*3600,3600)
            stop.wait(delay)
    thread=threading.Thread(target=worker,name='erp-backup',daemon=True)
    thread.start()
    return thread


if __name__=='__main__':
    os.umask(0o077)
    parser=argparse.ArgumentParser(description='Create and verify a consistent ERP backup')
    parser.add_argument('--directory')
    parser.add_argument('--retain',type=int,default=14)
    args=parser.parse_args()
    if not erp.DB_PATH.exists():
        raise SystemExit('Database does not exist; initialize the environment first.')
    print(create_backup(args.directory,args.retain))
