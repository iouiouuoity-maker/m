#!/usr/bin/env python3
"""ErrorMap classroom server. Python 3.12+, standard library only."""
import os, json, sqlite3, secrets, hashlib, hmac, time, re, smtplib, threading, argparse
from pathlib import Path
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from email.message import EmailMessage
from http.cookies import SimpleCookie
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
DATA = Path('/tmp/errormap') if os.environ.get('VERCEL') else Path(os.environ.get('ERRORMAP_DATA', ROOT / 'data'))
DATA.mkdir(parents=True, exist_ok=True)
DB = DATA / 'classroom.sqlite3'
BANK = json.loads((ROOT / 'dist/assets/question-bank.json').read_text())
LOCK = threading.Lock()
RATE = {}

def conn():
    if os.environ.get('DATABASE_URL'):
        from server.postgres import connect
        return connect()
    return sqlite_conn()

def sqlite_conn():
    c = sqlite3.connect(DB, timeout=15)
    c.row_factory = sqlite3.Row
    c.execute('PRAGMA foreign_keys=ON')
    return c

def init():
    with conn() as c:
        if os.environ.get('DATABASE_URL'):c.execute('BEGIN IMMEDIATE')
        c.executescript('''
        PRAGMA journal_mode=WAL;
        CREATE TABLE IF NOT EXISTS users(id TEXT PRIMARY KEY, role TEXT NOT NULL, name TEXT NOT NULL, login TEXT UNIQUE NOT NULL, password TEXT NOT NULL, class_id TEXT, email TEXT NOT NULL DEFAULT '');
        CREATE TABLE IF NOT EXISTS classes(id TEXT PRIMARY KEY, teacher_id TEXT NOT NULL REFERENCES users(id), name TEXT NOT NULL, code TEXT UNIQUE NOT NULL);
        CREATE TABLE IF NOT EXISTS sessions(token TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id), expires INTEGER NOT NULL);
        CREATE TABLE IF NOT EXISTS questions(id TEXT PRIMARY KEY, teacher_id TEXT NOT NULL REFERENCES users(id), payload TEXT NOT NULL, archived INTEGER NOT NULL DEFAULT 0);
        CREATE TABLE IF NOT EXISTS assignments(id TEXT PRIMARY KEY, class_id TEXT NOT NULL REFERENCES classes(id), title TEXT NOT NULL, questions TEXT NOT NULL, published INTEGER NOT NULL DEFAULT 0, created INTEGER NOT NULL);
        CREATE TABLE IF NOT EXISTS attempts(id TEXT PRIMARY KEY, assignment_id TEXT NOT NULL REFERENCES assignments(id), user_id TEXT NOT NULL REFERENCES users(id), snapshot TEXT NOT NULL, answers TEXT NOT NULL, result TEXT, created INTEGER NOT NULL, submitted INTEGER, UNIQUE(assignment_id,user_id));
        CREATE TABLE IF NOT EXISTS mail(id TEXT PRIMARY KEY, attempt_id TEXT UNIQUE NOT NULL REFERENCES attempts(id), status TEXT NOT NULL DEFAULT 'waiting', tries INTEGER NOT NULL DEFAULT 0, next_try INTEGER NOT NULL DEFAULT 0, error TEXT NOT NULL DEFAULT '');
        ''')

def token(): return secrets.token_urlsafe(24)
def digest(value): return hashlib.sha256(value.encode()).hexdigest()
def password(value, salt=None):
    salt = salt or secrets.token_hex(16)
    return salt + ':' + hashlib.scrypt(value.encode(), salt=bytes.fromhex(salt), n=16384, r=8, p=1).hex()
def verify(value, stored): return hmac.compare_digest(password(value, stored.split(':')[0]), stored)
def clean(v, lo=1, hi=120):
    if not isinstance(v,str) or not lo <= len(v.strip()) <= hi: raise ValueError('Invalid text length')
    return v.strip()
def pw(v):
    if not isinstance(v,str) or not 10 <= len(v) <= 128: raise ValueError('Password must contain 10–128 characters')
    return v

def public_question(q): return {k:q[k] for k in ('id','prompt','options','unit','level')}
def validate_question(q):
    if not isinstance(q,dict): raise ValueError('Invalid question')
    prompt=clean(q.get('prompt'),3,1000)
    options=q.get('options')
    if not isinstance(options,list) or len(options)!=3: raise ValueError('Exactly three options required')
    options=[clean(o,1,300) for o in options]
    if len(set(options))!=3 or type(q.get('answer')) is not int or q['answer'] not in range(3): raise ValueError('Invalid options or answer')
    if q.get('unit') not in {u['id'] for u in BANK['units']}: raise ValueError('Unknown rule')
    if type(q.get('level')) is not int or q['level'] not in (1,2,3): raise ValueError('Invalid difficulty')
    return dict(prompt=prompt,options=options,answer=q['answer'],unit=q['unit'],level=q['level'],explanation=clean(q.get('explanation'),3,1500))

def all_questions(c, teacher):
    qs={q['id']:{**q,'editable':False} for q in BANK['questions']}
    for row in c.execute('SELECT id,payload FROM questions WHERE teacher_id=? AND archived=0',(teacher,)):
        qs[row['id']]={**json.loads(row['payload']),'editable':True}
    return qs

class Handler(SimpleHTTPRequestHandler):
    def __init__(self,*args,**kwargs): super().__init__(*args,directory=str(ROOT/'dist'),**kwargs)
    def log_message(self, fmt, *args): pass
    def end_headers(self):
        self.send_header('X-Content-Type-Options','nosniff')
        self.send_header('Referrer-Policy','same-origin')
        self.send_header('X-Frame-Options','DENY')
        if self.path.startswith('/api/'): self.send_header('Cache-Control','no-store')
        super().end_headers()
    def send_json(self, data, status=200, cookie=None):
        body=json.dumps(data,ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header('Content-Type','application/json; charset=utf-8')
        self.send_header('Content-Length',str(len(body)))
        if cookie: self.send_header('Set-Cookie',cookie)
        self.end_headers(); self.wfile.write(body)
    def body(self):
        n=int(self.headers.get('Content-Length','0'))
        if not 0<n<=100000: raise ValueError('Invalid request size')
        data=json.loads(self.rfile.read(n))
        if not isinstance(data,dict): raise ValueError('Invalid JSON object')
        return data
    def session(self,c):
        cookie=SimpleCookie()
        try: cookie.load(self.headers.get('Cookie',''))
        except Exception: return None
        sid=cookie.get('errormap_session')
        if not sid:return None
        return c.execute('SELECT u.* FROM sessions s JOIN users u ON u.id=s.user_id WHERE s.token=? AND s.expires>?',(digest(sid.value),int(time.time()))).fetchone()
    def set_session(self,c,user):
        sid=token(); c.execute('DELETE FROM sessions WHERE expires<?',(int(time.time()),))
        c.execute('INSERT INTO sessions VALUES(?,?,?)',(digest(sid),user,int(time.time())+43200))
        return 'errormap_session='+sid+'; Path=/; HttpOnly; SameSite=Strict; Max-Age=43200'+('; Secure' if os.environ.get('ERRORMAP_SECURE_COOKIE')=='1' else '')
    def origin_ok(self):
        origin=self.headers.get('Origin')
        if not origin:return True
        return origin==os.environ.get('ERRORMAP_ORIGIN','http://'+self.headers.get('Host',''))
    def do_GET(self):
        if self.path.startswith('/api/'):return self.api('GET')
        if urlparse(self.path).path=='/':
            self.send_response(302);self.send_header('Location','/index.html');self.send_header('Content-Length','0');self.end_headers();return
        return super().do_GET()
    def do_POST(self):self.api('POST')
    def do_PUT(self):self.api('PUT')
    def do_DELETE(self):self.api('DELETE')
    def api(self,method):
        try:
            if method!='GET' and not self.origin_ok():return self.send_json({'error':'Origin rejected'},403)
            path=urlparse(self.path).path
            data=self.body() if method in ('POST','PUT') else {}
            with conn() as c:
                result,status,cookie=self.route(c,method,path,data)
            return self.send_json(result,status,cookie)
        except (ValueError,KeyError,TypeError,json.JSONDecodeError):return self.send_json({'error':'Check the entered values and try again'},400)
        except sqlite3.IntegrityError:return self.send_json({'error':'This login or record already exists'},409)
        except Exception:return self.send_json({'error':'Server error. Please try again'},500)
    def route(self,c,m,p,d):
        if m=='GET' and p=='/api/status':return {'setup':not bool(c.execute("SELECT 1 FROM users WHERE role='teacher'").fetchone())},200,None
        if m=='POST' and p in ('/api/setup','/api/login','/api/join'):
            key=self.client_address[0]
            with LOCK:
                RATE[key]=[t for t in RATE.get(key,[]) if t>time.time()-300]
                if len(RATE[key])>=25:return {'error':'Too many attempts. Wait five minutes'},429,None
                RATE[key].append(time.time())
            if p=='/api/setup':
                # Write lock makes first-teacher creation atomic.
                c.execute('BEGIN IMMEDIATE')
                if c.execute("SELECT 1 FROM users WHERE role='teacher'").fetchone():return {'error':'Teacher already configured'},409,None
                expected=os.environ.get('ERRORMAP_SETUP_TOKEN','')
                if not expected or not hmac.compare_digest(str(d.get('setupToken','')),expected):return {'error':'Enter the server setup token'},403,None
                user=token(); c.execute('INSERT INTO users(id,role,name,login,password) VALUES(?,?,?,?,?)',(user,'teacher',clean(d.get('name')),clean(d.get('login')).lower(),password(pw(d.get('password')))))
            elif p=='/api/join':
                cl=c.execute('SELECT * FROM classes WHERE code=?',(clean(d.get('code')).upper(),)).fetchone()
                if not cl:return {'error':'Class code not found'},404,None
                user=token();c.execute('INSERT INTO users(id,role,name,login,password,class_id) VALUES(?,?,?,?,?,?)',(user,'student',clean(d.get('name')),clean(d.get('login')).lower(),password(pw(d.get('password'))),cl['id']))
            else:
                row=c.execute('SELECT * FROM users WHERE login=?',(clean(d.get('login')).lower(),)).fetchone()
                if not row or not verify(str(d.get('password','')),row['password']):return {'error':'Incorrect login or password'},401,None
                if d.get('role') in ('student','teacher') and row['role']!=d['role']:return {'error':'Use the correct student or teacher sign-in page'},403,None
                user=row['id']
            return {'ok':True},200,self.set_session(c,user)
        u=self.session(c)
        if not u:return {'error':'Sign in to continue'},401,None
        teacher=u['role']=='teacher'
        if m=='GET' and p=='/api/rules':return BANK['units'],200,None
        if m=='GET' and p=='/api/me':return {k:u[k] for k in ('id','role','name','email')},200,None
        if m=='POST' and p=='/api/logout':
            ck=SimpleCookie(self.headers.get('Cookie',''));c.execute('DELETE FROM sessions WHERE token=?',(digest(ck['errormap_session'].value),))
            return {'ok':True},200,'errormap_session=; Path=/; HttpOnly; SameSite=Strict; Max-Age=0'
        if m=='PUT' and p=='/api/password':
            if not verify(str(d.get('current','')),u['password']):return {'error':'Current password is incorrect'},403,None
            c.execute('UPDATE users SET password=? WHERE id=?',(password(pw(d.get('password'))),u['id']))
            c.execute('DELETE FROM sessions WHERE user_id=?',(u['id'],))
            return {'ok':True},200,self.set_session(c,u['id'])
        if teacher:return self.teacher(c,u,m,p,d)
        return self.student(c,u,m,p,d)
    def teacher(self,c,u,m,p,d):
        if p=='/api/settings' and m=='PUT':
            email=str(d.get('email','')).strip()
            if email and (len(email)>254 or not re.fullmatch(r'[^\s@<>]+@[^\s@<>]+\.[^\s@<>]+',email)):raise ValueError()
            c.execute('UPDATE users SET email=? WHERE id=?',(email,u['id']))
            return {'ok':True,'mailConfigured':bool(os.environ.get('SMTP_HOST'))},200,None
        if p=='/api/classes':
            if m=='POST':c.execute('INSERT INTO classes VALUES(?,?,?,?)',(token(),u['id'],clean(d.get('name')),secrets.token_hex(4).upper()))
            return [dict(r) for r in c.execute("SELECT cl.id,cl.name,cl.code,(SELECT count(*) FROM users WHERE class_id=cl.id AND role='student') AS student_count FROM classes cl WHERE teacher_id=?",(u['id'],))],200,None
        if p=='/api/questions':
            if m=='POST':
                q=validate_question(d);q['id']=token()
                c.execute('INSERT INTO questions(id,teacher_id,payload) VALUES(?,?,?)',(q['id'],u['id'],json.dumps(q)))
            return {'questions':list(all_questions(c,u['id']).values()),'units':BANK['units']},200,None
        match=re.fullmatch('/api/questions/([^/]+)',p)
        if match and m in ('PUT','DELETE'):
            qid=match[1]
            if not c.execute('SELECT 1 FROM questions WHERE id=? AND teacher_id=?',(qid,u['id'])).fetchone():return {'error':'Duplicate a bank question before editing it'},403,None
            if m=='DELETE':c.execute('UPDATE questions SET archived=1 WHERE id=?',(qid,))
            else:
                q=validate_question(d);q['id']=qid;c.execute('UPDATE questions SET payload=? WHERE id=? AND teacher_id=?',(json.dumps(q),qid,u['id']))
            return {'ok':True},200,None
        if p=='/api/assignments':
            if m=='POST':
                cl=c.execute('SELECT id FROM classes WHERE id=? AND teacher_id=?',(d.get('class_id'),u['id'])).fetchone()
                ids=d.get('questions');bank=all_questions(c,u['id'])
                if not cl or not isinstance(ids,list) or not 1<=len(ids)<=100 or len(set(ids))!=len(ids) or any(i not in bank for i in ids):raise ValueError()
                # Immutable assignment snapshot preserves grading after question edits.
                c.execute('INSERT INTO assignments VALUES(?,?,?,?,?,?)',(token(),cl['id'],clean(d.get('title')),json.dumps([bank[i] for i in ids]),0,int(time.time())))
            rows=c.execute('SELECT a.id,a.title,a.published,a.class_id,cl.name AS class_name FROM assignments a JOIN classes cl ON cl.id=a.class_id WHERE cl.teacher_id=? ORDER BY a.created DESC',(u['id'],))
            return [dict(r) for r in rows],200,None
        match=re.fullmatch('/api/assignments/([^/]+)',p)
        if match and m in ('GET','PUT'):
            a=c.execute('SELECT * FROM assignments WHERE id=? AND class_id IN (SELECT id FROM classes WHERE teacher_id=?)',(match[1],u['id'])).fetchone()
            if not a:return {'error':'Assignment not found'},404,None
            if m=='GET':return {**dict(a),'questions':json.loads(a['questions'])},200,None
            if a['published']:return {'error':'Published assignments cannot be changed'},409,None
            ids=d.get('questions');bank=all_questions(c,u['id'])
            bank={**{q['id']:q for q in json.loads(a['questions'])},**bank}
            if not isinstance(ids,list) or not 1<=len(ids)<=100 or len(set(ids))!=len(ids) or any(i not in bank for i in ids):raise ValueError()
            c.execute('UPDATE assignments SET title=?,questions=? WHERE id=?',(clean(d.get('title')),json.dumps([bank[i] for i in ids]),a['id']))
            return {'ok':True},200,None
        match=re.fullmatch('/api/assignments/([^/]+)/publish',p)
        if match and m=='POST':
            changed=c.execute('UPDATE assignments SET published=1 WHERE id=? AND class_id IN (SELECT id FROM classes WHERE teacher_id=?)',(match[1],u['id'])).rowcount
            return ({'ok':True},200,None) if changed else ({'error':'Assignment not found'},404,None)
        if p=='/api/results' and m=='GET':
            rows=c.execute('''SELECT t.id,t.submitted,t.result,a.title,u.name,cl.name AS class_name,COALESCE(mail.status,'none') AS email_status FROM attempts t JOIN users u ON u.id=t.user_id JOIN assignments a ON a.id=t.assignment_id JOIN classes cl ON cl.id=a.class_id LEFT JOIN mail ON mail.attempt_id=t.id WHERE cl.teacher_id=? AND t.submitted IS NOT NULL ORDER BY t.submitted DESC''',(u['id'],))
            return [{**dict(r),'result':json.loads(r['result'])} for r in rows],200,None
        if p=='/api/mail/retry' and m=='POST':
            c.execute("UPDATE mail SET status='waiting',tries=0,next_try=0 WHERE status IN ('waiting','failed') AND attempt_id IN (SELECT t.id FROM attempts t JOIN assignments a ON a.id=t.assignment_id JOIN classes cl ON cl.id=a.class_id WHERE cl.teacher_id=?)",(u['id'],))
            return {'ok':True},200,None
        return {'error':'Not found'},404,None
    def student(self,c,u,m,p,d):
        if p=='/api/assignments' and m=='GET':
            rows=c.execute('''SELECT a.id,a.title,t.submitted,t.result,t.created AS started,json_array_length(a.questions) AS question_count FROM assignments a LEFT JOIN attempts t ON t.assignment_id=a.id AND t.user_id=? WHERE a.class_id=? AND a.published=1 ORDER BY a.created DESC''',(u['id'],u['class_id']))
            return [{**dict(r),'result':json.loads(r['result']) if r['result'] else None} for r in rows],200,None
        match=re.fullmatch('/api/assignments/([^/]+)/start',p)
        if match and m=='POST':
            c.execute('BEGIN IMMEDIATE')
            a=c.execute('SELECT * FROM assignments WHERE id=? AND class_id=? AND published=1',(match[1],u['class_id'])).fetchone()
            if not a:return {'error':'Assignment not found'},404,None
            t=c.execute('SELECT * FROM attempts WHERE assignment_id=? AND user_id=?',(a['id'],u['id'])).fetchone()
            if not t:
                qs=json.loads(a['questions'])
                for q in qs:
                    order=list(range(3));secrets.SystemRandom().shuffle(order)
                    q['options']=[q['options'][i] for i in order];q['answer']=order.index(q['answer'])
                attempt=token();c.execute('INSERT INTO attempts(id,assignment_id,user_id,snapshot,answers,created) VALUES(?,?,?,?,?,?)',(attempt,a['id'],u['id'],json.dumps(qs),json.dumps([None]*len(qs)),int(time.time())))
                t=c.execute('SELECT * FROM attempts WHERE id=?',(attempt,)).fetchone()
            return self.attempt_payload(t,a['title']),200,None
        match=re.fullmatch('/api/attempts/([^/]+)(/submit)?',p)
        if match and m=='PUT':
            c.execute('BEGIN IMMEDIATE')
            t=c.execute('SELECT * FROM attempts WHERE id=? AND user_id=?',(match[1],u['id'])).fetchone()
            if not t:return {'error':'Attempt not found'},404,None
            if t['submitted']:return {'error':'Already submitted'},409,None
            qs=json.loads(t['snapshot']);answers=d.get('answers')
            if not isinstance(answers,list) or len(answers)!=len(qs) or any(x is not None and (type(x) is not int or x not in range(3)) for x in answers):raise ValueError()
            if match[2]:
                if None in answers:return {'error':'Answer every question before submitting'},400,None
                details=[dict(unit=q['unit'],prompt=q['prompt'],selected=q['options'][v],answer=q['options'][q['answer']],correct=v==q['answer'],explanation=q['explanation']) for q,v in zip(qs,answers)]
                result=dict(score=sum(x['correct'] for x in details),total=len(qs),details=details)
                c.execute('UPDATE attempts SET answers=?,result=?,submitted=? WHERE id=?',(json.dumps(answers),json.dumps(result),int(time.time()),t['id']))
                c.execute('INSERT OR IGNORE INTO mail(id,attempt_id) VALUES(?,?)',(token(),t['id']))
                return {'result':result},200,None
            c.execute('UPDATE attempts SET answers=? WHERE id=?',(json.dumps(answers),t['id']))
            return {'ok':True},200,None
        return {'error':'Not found'},404,None
    def attempt_payload(self,t,title):
        return dict(id=t['id'],title=title,questions=[public_question(q) for q in json.loads(t['snapshot'])],answers=json.loads(t['answers']),result=json.loads(t['result']) if t['result'] else None)

def deliver_mail(limit=10):
    """Durable outbox. SMTP is at-least-once if a crash occurs after delivery."""
    host=os.environ.get('SMTP_HOST');sender=os.environ.get('SMTP_FROM')
    if not host or not sender:return
    with conn() as c:
        rows=c.execute('''SELECT mail.*,t.result,t.submitted,u.name,a.title,cl.name AS class_name,teacher.email FROM mail JOIN attempts t ON t.id=mail.attempt_id JOIN users u ON u.id=t.user_id JOIN assignments a ON a.id=t.assignment_id JOIN classes cl ON cl.id=a.class_id JOIN users teacher ON teacher.id=cl.teacher_id WHERE (mail.status='waiting' OR mail.status='sending') AND mail.next_try<=? AND teacher.email!='' ORDER BY t.submitted ASC LIMIT ?''',(int(time.time()),limit)).fetchall()
    for r in rows:
        with conn() as c:
            claimed=c.execute("UPDATE mail SET status='sending',next_try=? WHERE id=? AND status IN ('waiting','sending') AND next_try<=?",(int(time.time())+120,r['id'],int(time.time()))).rowcount
        if not claimed:continue
        try:
            result=json.loads(r['result']);msg=EmailMessage();msg['From']=sender;msg['To']=r['email'];msg['Subject']='ErrorMap: '+r['name']+' — '+r['title'];msg['Message-ID']='<'+r['id']+'@errormap.local>'
            lines=[f"Student: {r['name']}",f"Class: {r['class_name']}",f"Assignment: {r['title']}",f"Score: {result['score']}/{result['total']}",'']
            for n,x in enumerate(result['details'],1):lines.extend([f"{n}. {x['prompt']}",f"Student answer: {x['selected']}",f"Correct answer: {x['answer']}",f"Result: {'Correct' if x['correct'] else 'Review'}",x['explanation'],''])
            msg.set_content('\n'.join(lines))
            ssl=os.environ.get('SMTP_SSL')=='1';client=smtplib.SMTP_SSL if ssl else smtplib.SMTP
            with client(host,int(os.environ.get('SMTP_PORT','465' if ssl else '587')),timeout=20) as smtp:
                if not ssl:smtp.starttls()
                if os.environ.get('SMTP_USER'):smtp.login(os.environ['SMTP_USER'],os.environ.get('SMTP_PASSWORD',''))
                smtp.send_message(msg)
            with conn() as c:c.execute("UPDATE mail SET status='sent',error='' WHERE id=?",(r['id'],))
        except Exception:
            tries=r['tries']+1
            with conn() as c:c.execute('UPDATE mail SET tries=?,status=?,next_try=?,error=? WHERE id=?',(tries,'failed' if tries>=5 else 'waiting',int(time.time())+min(3600,60*2**tries),'Delivery failed. Check SMTP settings.',r['id']))

def mail_loop(stop):
    while not stop.is_set():
        try:deliver_mail()
        except Exception:pass
        stop.wait(30)

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--strictPort',action='store_true',help=argparse.SUPPRESS);parser.add_argument('--host',default='127.0.0.1');parser.add_argument('--port',type=int,default=int(os.environ.get('PORT','8000')));args=parser.parse_args()
    init();stop=threading.Event();threading.Thread(target=mail_loop,args=(stop,),daemon=True).start()
    server=ThreadingHTTPServer((args.host,args.port),Handler)
    print(f'ErrorMap classroom: http://{args.host}:{args.port}',flush=True)
    try:server.serve_forever()
    except KeyboardInterrupt:pass
    finally:stop.set();server.server_close()
