"""User-owned UDisks image mounting; fail closed when permanent storage is absent."""
import json,os,re,subprocess,sys
from pathlib import Path
from dotenv import load_dotenv


def ensure_mount(image,root,expected_uuid):
    image=Path(image).resolve();root=Path(root)
    if not image.is_file() or not expected_uuid:raise RuntimeError('Archive image/configuration unavailable')
    def matches():
        r=subprocess.run(['findmnt','-n','-T',str(root),'-o','FSTYPE,UUID,TARGET'],capture_output=True,text=True)
        fields=r.stdout.split()
        return len(fields)==3 and fields[0]=='ext4' and fields[1]==expected_uuid and Path(fields[2])==root
    if matches():return
    devices=[]
    for p in Path('/sys/block').glob('loop*/loop/backing_file'):
        try:backing=Path('/'+p.read_text().strip().lstrip('/')).resolve()
        except (OSError,RuntimeError):continue
        if backing==image:devices.append('/dev/'+p.parent.parent.name)
    if len(devices)>1:raise RuntimeError('Archive image has multiple mappings; inspect before mounting')
    if not devices:
        r=subprocess.run(['udisksctl','loop-setup','--no-user-interaction','--file',str(image)],capture_output=True,text=True,check=True)
        match=re.search(r'as (/dev/loop\d+)\.',r.stdout)
        if not match:raise RuntimeError('Disk service did not report an image device')
        devices=[match.group(1)]
    subprocess.run(['udisksctl','mount','--no-user-interaction','--block-device',devices[0]],capture_output=True,check=True)
    if not matches():raise RuntimeError('Archive mount/UUID differs; refuse fallback storage')


def main():
    load_dotenv()
    try:
        ensure_mount(os.environ['ARCHIVE_IMAGE'],os.environ['ARCHIVE_ROOT'],os.environ['ARCHIVE_FILESYSTEM_UUID'])
        print(json.dumps(dict(stage='ARCHIVE_MOUNT_READY')));return 0
    except Exception as e:print(json.dumps(dict(stage='ARCHIVE_MOUNT_STOPPED',error_type=type(e).__name__)),file=sys.stderr);return 1


if __name__=='__main__':raise SystemExit(main())
