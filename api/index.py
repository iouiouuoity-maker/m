"""Vercel Python Function, routed from /api/* by vercel.json."""
import os, sys, threading, hmac
from pathlib import Path
from urllib.parse import urlparse, parse_qs
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from server import server as app

_ready=False
_init_lock=threading.Lock()

class handler(app.Handler):
    def _prepare(self):
        global _ready
        # Never silently replace durable storage with /tmp SQLite on Vercel.
        if not os.environ.get('DATABASE_URL'):
            self.send_json({'error':'Classroom database is not connected yet'},503)
            return False
        try:
            if not _ready:
                with _init_lock:
                    if not _ready:app.init();_ready=True
        except Exception:
            self.send_json({'error':'Classroom database is unavailable'},503)
            return False
        qs=parse_qs(urlparse(self.path).query)
        route=qs.get('route',[None])[0]
        if route is not None:self.path='/api/'+route.lstrip('/')
        return True
    def api(self,method):
        if not self._prepare():return
        if urlparse(self.path).path=='/api/mail/cron':
            secret=os.environ.get('CRON_SECRET','')
            if method!='GET' or not secret or not hmac.compare_digest(self.headers.get('Authorization',''),'Bearer '+secret):return self.send_json({'error':'Not authorized'},401)
            try:app.deliver_mail(limit=1);return self.send_json({'ok':True})
            except Exception:return self.send_json({'error':'Mail processing unavailable'},503)
        # Complete the bounded delivery before returning; never rely on a daemon
        # thread continuing after a serverless response.
        original=self.send_json
        def send_then_finish(data,status=200,cookie=None):
            if method in ('PUT','POST') and status<300 and (self.path.endswith('/submit') or self.path in ('/api/settings','/api/mail/retry')):
                try:app.deliver_mail(limit=1)
                except Exception:pass # Grade is already committed; outbox persists.
            return original(data,status,cookie)
        self.send_json=send_then_finish
        return super().api(method)
    def do_GET(self):self.api('GET')
