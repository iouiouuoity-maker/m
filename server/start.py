#!/usr/bin/env python3
"""Load optional .env, create a first-run setup token, then start ErrorMap."""
import os, runpy, secrets
from pathlib import Path
root=Path(__file__).resolve().parents[1]
config=root/'.env'
if config.exists():
    for line in config.read_text().splitlines():
        line=line.strip()
        if not line or line.startswith('#'):continue
        key,sep,value=line.partition('=')
        if sep and key.strip().replace('_','').isalnum():
            value=value.strip()
            if len(value)>=2 and value[0]==value[-1] and value[0] in ('"',"'"):value=value[1:-1]
            os.environ.setdefault(key.strip(),value)
if not os.environ.get('ERRORMAP_SETUP_TOKEN'):
    os.environ['ERRORMAP_SETUP_TOKEN']=secrets.token_urlsafe(32)
# Only show this server-side token before any teacher exists.
import importlib.util
spec=importlib.util.spec_from_file_location('errormap_server',root/'server/server.py')
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);module.init()
with module.conn() as c:
    if not c.execute("SELECT 1 FROM users WHERE role='teacher'").fetchone():
        print('First-time teacher setup token: '+os.environ['ERRORMAP_SETUP_TOKEN'],flush=True)
runpy.run_path(str(root/'server/server.py'),run_name='__main__')
