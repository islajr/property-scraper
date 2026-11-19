"""Install per-user archive, publisher and backup units; activation is explicit."""
import json,os,shutil,subprocess
from datetime import datetime,timezone
from pathlib import Path
from dotenv import dotenv_values


def quoted(path):
    return '"'+str(path).replace('%','%%').replace('\\','\\\\').replace('"','\\"')+'"'


def main():
    root=Path(__file__).resolve().parents[1];env=dotenv_values(root/'.env');archive=Path(env['ARCHIVE_ROOT'])
    target=Path.home()/'.config/systemd/user';target.mkdir(parents=True,exist_ok=True)
    python=quoted(root/'.venv/bin/python');work=str(root).replace('%','%%');envfile=quoted(root/'.env')
    common=f'WorkingDirectory={work}\nEnvironmentFile={envfile}\n'
    pgctl=quoted(shutil.which('pg_ctl'));data=quoted(archive/'postgres');log=quoted(archive/'postgres-server.log')
    units={
      'property-scraper-archive.service':f'''[Unit]\nDescription=Property scraper permanent local archive\n[Service]\nType=forking\n{common}ExecStartPre={python} -m scripts.ensure_archive_mount\nExecStart={pgctl} -D {data} -l {log} -w start\nExecStop={pgctl} -D {data} -m fast -w stop\nPIDFile={str(archive/'postgres/postmaster.pid').replace('%','%%')}\nRestart=on-failure\nRestartSec=30\nTimeoutStartSec=120\nTimeoutStopSec=120\n[Install]\nWantedBy=default.target\n''',
      'property-scraper-publisher.service':f'''[Unit]\nDescription=Publish current shared property data\nRequires=property-scraper-archive.service\nAfter=property-scraper-archive.service\n[Service]\nType=oneshot\n{common}ExecStart={python} -m scripts.publish_shared_data publish\nTimeoutStartSec=900\n''',
      'property-scraper-publisher.timer':'''[Unit]\nDescription=Retry shared property publication every fifteen minutes\n[Timer]\nOnCalendar=*:0/15\nPersistent=true\n[Install]\nWantedBy=timers.target\n''',
      'property-scraper-backup.service':f'''[Unit]\nDescription=Back up full property archive to independent storage\nRequires=property-scraper-archive.service\nAfter=property-scraper-archive.service\n[Service]\nType=oneshot\n{common}ExecStart={python} -m scripts.backup_local_archive\nTimeoutStartSec=1800\n''',
      'property-scraper-backup.timer':'''[Unit]\nDescription=Daily full property archive backup\n[Timer]\nOnCalendar=*-*-* 04:30:00\nPersistent=true\n[Install]\nWantedBy=timers.target\n''',
      'scraper-health.service.d/archive.conf':'''[Unit]\nRequires=property-scraper-archive.service\nAfter=property-scraper-archive.service\n'''
    }
    previous=archive/'repair-artifacts'/('service-config-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ'));previous.mkdir(parents=True,mode=0o700)
    for name,content in units.items():
        p=target/name;p.parent.mkdir(parents=True,exist_ok=True)
        if p.exists():shutil.copy2(p,previous/name.replace('/','_'))
        p.write_text(content);os.chmod(p,0o600)
    subprocess.run(['systemctl','--user','daemon-reload'],check=True)
    print(json.dumps(dict(stage='ARCHIVE_UNITS_INSTALLED_NOT_ACTIVATED',units=list(units))))


if __name__=='__main__':main()
