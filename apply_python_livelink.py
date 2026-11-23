"""Install the reviewed Python Live Link Stream extension without a git update.

Close RGB MoCap first. Run with its runtime/python.exe and --root APP_FOLDER.
No runtime packages, models, caches, settings or inference code are changed.
"""
from pathlib import Path
import argparse
import ast
import hashlib
import json
import sys
import time
import uuid

from integrate_stream import integrate, MARKER

HERE=Path(__file__).resolve().parent
FILES=('mocap/python_livelink.py','mocap/python_livelink_wire.py',
       'mocap/python_livelink_rig.py','mocap/python_livelink_ui.py',
       'docs/PYTHON_LIVE_LINK.md')

def digest(text): return hashlib.sha256((text.rstrip('\n')+'\n').encode('utf8')).hexdigest()

def plan(root):
    root=Path(root).resolve()
    stream=root/'mocap/stream_ui.py'
    current=stream.read_text(encoding='utf8')
    before={name:(root/name).read_bytes() if (root/name).exists() else None for name in FILES}
    payload={name:(HERE/name).read_bytes() for name in FILES}
    if MARKER in current:
        if all(before[name]==payload[name] for name in FILES): return {},{}
        raise ValueError('A different Python Live Link revision is installed; no files changed.')
    allowed=json.loads((HERE/'stream_baselines.json').read_text(encoding='utf8'))
    if digest(current) not in allowed:
        raise ValueError('Unreviewed Stream source version; no files changed.')
    for name in FILES:
        if before[name] is not None and before[name]!=payload[name]:
            raise ValueError('Existing file differs: '+name)
    payload['mocap/stream_ui.py']=integrate(current).encode('utf8')
    before['mocap/stream_ui.py']=stream.read_bytes()
    for name,data in payload.items():
        if name.endswith('.py'): ast.parse(data,filename=name)
    return before,payload

def install(root,dry_run=False):
    root=Path(root).resolve(); before,payload=plan(root)
    if not payload:
        print('Python Live Link already installed.'); return
    if dry_run:
        print('Ready: '+', '.join(payload)); return
    sys.path.insert(0,str(root))
    from tools.session_lock import app_lock
    with app_lock(root):
        for name,data in before.items():
            target=root/name
            if (target.read_bytes() if target.exists() else None)!=data:
                raise ValueError('Source changed during validation; no files changed.')
        backup=root/'local_patches'/('python-livelink-'+time.strftime('%Y%m%d-%H%M%S')+'-'+uuid.uuid4().hex[:8])
        backup.mkdir(parents=True,exist_ok=False)
        for name,data in before.items():
            if data is not None:
                target=backup/name; target.parent.mkdir(parents=True,exist_ok=True); target.write_bytes(data)
        (backup/'manifest.json').write_text(json.dumps({name:None if data is None else hashlib.sha256(data).hexdigest()
            for name,data in before.items()},indent=2),encoding='utf8')
        written=[]
        try:
            for name,data in payload.items():
                target=root/name; target.parent.mkdir(parents=True,exist_ok=True)
                written.append(name); target.write_bytes(data)
        except BaseException:
            for name in reversed(written):
                target=root/name
                if before[name] is None: target.unlink(missing_ok=True)
                else: target.write_bytes(before[name])
            raise
    print('Installed. Stream > Target > Python Live Link (SaintMocap).')
    print('Backup: '+str(backup))

if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--root',type=Path,default=Path(r'E:\RGBMoCap'))
    parser.add_argument('--dry-run',action='store_true')
    args=parser.parse_args()
    try: install(args.root,args.dry_run)
    except (OSError,ValueError,RuntimeError) as exc:
        print('Not applied: '+str(exc),file=sys.stderr); sys.exit(1)
