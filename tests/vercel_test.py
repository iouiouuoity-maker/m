"""Serverless configuration and SQL adapter checks; no external DB credentials."""
import sys,json,unittest,importlib.util
from pathlib import Path
from http.server import ThreadingHTTPServer
from urllib.request import urlopen
from urllib.error import HTTPError
from unittest.mock import patch
import threading
r=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(r))
from server.postgres import translate
class VercelTest(unittest.TestCase):
 def test_sql_dialect(self):
  self.assertIsNone(translate('PRAGMA journal_mode=WAL'))
  self.assertIn('pg_advisory_xact_lock',translate('BEGIN IMMEDIATE'))
  self.assertEqual(translate('INSERT OR IGNORE INTO mail VALUES(?,?)'),'INSERT INTO mail VALUES(%s,%s) ON CONFLICT DO NOTHING')
  self.assertIn('jsonb_array_length(a.questions::jsonb)',translate('SELECT json_array_length(a.questions) FROM assignments a'))
 def test_deployment_contract(self):
  config=json.loads((r/'vercel.json').read_text())
  self.assertEqual(config['outputDirectory'],'public')
  self.assertTrue((r/'api/index.py').is_file())
  self.assertIn('route=:path*',config['rewrites'][0]['destination'])
  self.assertEqual(config['crons'][0]['path'],'/api/mail/cron')
  self.assertIn('id="homeLogin"',(r/'dist/index.html').read_text())
  self.assertIn('id="guestButton"',(r/'dist/index.html').read_text())
 def test_no_ephemeral_fallback(self):
  spec=importlib.util.spec_from_file_location('vercel_handler',r/'api/index.py');module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
  http=ThreadingHTTPServer(('127.0.0.1',0),module.handler);thread=threading.Thread(target=http.serve_forever,daemon=True);thread.start()
  try:
   with patch.dict('os.environ',{'DATABASE_URL':''}):
    with self.assertRaises(HTTPError) as ctx:urlopen('http://127.0.0.1:'+str(http.server_port)+'/api/index.py?route=status')
    self.assertEqual(ctx.exception.code,503)
    self.assertIn('not connected',json.load(ctx.exception)['error'])
  finally:http.shutdown();http.server_close()
if __name__=='__main__':unittest.main()
