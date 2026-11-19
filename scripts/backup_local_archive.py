"""Back up the complete archive and immutable publication files to two volumes."""
import hashlib,json,os,shutil,subprocess,sys
from datetime import datetime,timezone
from pathlib import Path
from dotenv import load_dotenv
import psycopg2
from scraper.shared_publication import assert_archive


def main():
    load_dotenv();os.umask(0o077);conn=None
    try:
        root=Path(os.environ['ARCHIVE_ROOT']);other=Path(os.environ['ARCHIVE_BACKUP_COPY'])
        if not (root/'postgres/PG_VERSION').is_file():raise RuntimeError('Archive unavailable')
        if root.stat().st_dev==other.parent.stat().st_dev:raise RuntimeError('Independent backup must use another filesystem')
        other.mkdir(parents=True,mode=0o700,exist_ok=True)
        conn=psycopg2.connect(os.environ['DATABASE_URL'],connect_timeout=15)
        assert_archive(conn,os.environ['ARCHIVE_DATABASE_ID']);conn.rollback()
        with conn.cursor() as q:
            q.execute("SELECT pg_try_advisory_lock(hashtextextended('archive-backup-v1',0))")
            if not q.fetchone()[0]:raise RuntimeError('Another archive backup is active')
        conn.commit()
        stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ');path=root/'backups'/('archive-'+stamp+'.dump');tmp=path.with_suffix('.partial')
        # The local socket URL has no password; remote credentials never enter argv.
        params=conn.get_dsn_parameters();env=dict(os.environ)
        for key,name in [('host','PGHOST'),('port','PGPORT'),('dbname','PGDATABASE'),('user','PGUSER'),('password','PGPASSWORD')]:
            if params.get(key):env[name]=params[key]
        r=subprocess.run(['pg_dump','-Fc','-Z6','--no-password','-f',str(tmp)],env=env,capture_output=True)
        if r.returncode:raise RuntimeError('Archive dump failed')
        r=subprocess.run(['pg_restore','--list',str(tmp)],capture_output=True)
        if r.returncode:raise RuntimeError('Archive dump catalog invalid')
        with tmp.open('rb') as f:os.fsync(f.fileno())
        tmp.rename(path);dest=other/path.name;shutil.copy2(path,dest)
        with dest.open('rb') as f:os.fsync(f.fileno())
        digest=hashlib.sha256(path.read_bytes()).hexdigest()
        if hashlib.sha256(dest.read_bytes()).hexdigest()!=digest:raise RuntimeError('Independent backup copy differs')
        with conn.cursor() as q:q.execute('SELECT id::text FROM ops.shared_publications ORDER BY created_at');ids=[r[0] for r in q]
        conn.rollback()
        for pid in ids:
            src=root/'published'/pid;target=other/'published'/pid
            if not target.exists():shutil.copytree(src,target)
            if (src/'manifest.json').read_bytes()!=(target/'manifest.json').read_bytes():raise RuntimeError('Publication manifest backup differs')
            data=json.loads((src/'manifest.json').read_text())
            for table,item in data['files'].items():
                if hashlib.sha256((target/(table+'.csv.gz')).read_bytes()).hexdigest()!=item['sha256']:raise RuntimeError('Publication backup differs')
        for folder in [other/'published', *[(other/'published'/pid) for pid in ids]]:
            if folder.exists():
                for item in folder.iterdir():
                    if item.is_file():
                        with item.open('rb') as f:os.fsync(f.fileno())
                fd=os.open(folder,os.O_RDONLY)
                try:os.fsync(fd)
                finally:os.close(fd)
        record=dict(stage='ARCHIVE_BACKUP_VERIFIED',at=datetime.now(timezone.utc).isoformat(),backup=str(path),copy=str(dest),sha256=digest,publication_directories=len(ids))
        for p in [path.with_suffix('.json'),dest.with_suffix('.json')]:
            p.write_text(json.dumps(record,indent=2)+'\n')
            with p.open('rb') as f:os.fsync(f.fileno())
        for folder in [root/'backups',other]:
            for old in sorted(folder.glob('archive-*.dump'))[:-3]:old.unlink();old.with_suffix('.json').unlink(missing_ok=True)
        for folder in [root/'backups',other]:
            fd=os.open(folder,os.O_RDONLY)
            try:os.fsync(fd)
            finally:os.close(fd)
        print(json.dumps(record));return 0
    except Exception as e:print(json.dumps(dict(stage='ARCHIVE_BACKUP_STOPPED',error_type=type(e).__name__)),file=sys.stderr);return 1
    finally:
        if conn:conn.close()


if __name__=='__main__':raise SystemExit(main())
