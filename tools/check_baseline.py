"""Run untouched HEAD backend tests in an isolated checkout without real service access."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT=Path(__file__).resolve().parents[1]


def run():
    with tempfile.TemporaryDirectory(prefix='safety-baseline-') as directory:
        root=Path(directory).resolve()
        assert root.parent==Path(tempfile.gettempdir()).resolve()
        files=subprocess.check_output(['git','ls-tree','-r','--name-only','HEAD','backend'],cwd=ROOT).decode().splitlines()
        for name in files:
            if not name.endswith('.py'): continue
            target=root/name;target.parent.mkdir(parents=True,exist_ok=True)
            target.write_bytes(subprocess.check_output(['git','show',f'HEAD:{name}'],cwd=ROOT))
        env={**os.environ,'CAMERA_SOURCE':'','TEST_DATABASE_URL':'','DATABASE_URL':'',
             'MONITOR_STORAGE_DIR':str(root/'recordings'),'SAFETY_DB_PATH':str(root/'events.sqlite')}
        process=subprocess.run([sys.executable,'-m','unittest','discover','-s',str(root/'backend'),'-v'],
            cwd=root,env=env,capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=180)
        output=process.stdout+process.stderr
        (ROOT/'baseline-with-deps.log').write_text(output,encoding='utf-8')
        print(output[-6000:])
        return process.returncode


if __name__=='__main__': sys.exit(run())
