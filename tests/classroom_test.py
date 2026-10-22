"""Integration tests use a temporary database and a real local HTTP server."""
import unittest, tempfile, os, sys, threading, json, urllib.request, urllib.error, http.cookiejar, importlib.util
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
TEMP=tempfile.TemporaryDirectory()
os.environ['ERRORMAP_DATA']=TEMP.name
os.environ['ERRORMAP_SETUP_TOKEN']='integration-setup-token-2026'
spec=importlib.util.spec_from_file_location('classroom',ROOT/'server/server.py')
app=importlib.util.module_from_spec(spec);spec.loader.exec_module(app)
app.init()
server=app.ThreadingHTTPServer(('127.0.0.1',0),app.Handler)
threading.Thread(target=server.serve_forever,daemon=True).start()
BASE='http://127.0.0.1:'+str(server.server_port)

def client():return urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
def call(c,path,method='GET',data=None,origin=None):
    request=urllib.request.Request(BASE+'/api/'+path,data=json.dumps(data).encode() if data is not None else None,method=method,headers={'Content-Type':'application/json',**({'Origin':origin} if origin else {})})
    try:
        with c.open(request) as r:return r.status,json.load(r)
    except urllib.error.HTTPError as r:return r.code,json.load(r)

class ClassroomTest(unittest.TestCase):
 def test_complete_classroom(self):
    teacher=client();student=client();stranger=client()
    with teacher.open(BASE) as r:
        self.assertTrue(r.url.endswith('/index.html'))
        self.assertIn(b'classroom/student.html',r.read())
    with teacher.open(BASE+'/classroom/classroom.js') as r:self.assertEqual(r.status,200)
    self.assertEqual(call(teacher,'status')[1],{'setup':True})
    self.assertEqual(call(teacher,'setup','POST',{'name':'Teacher','login':'teacher','password':'secure-password','setupToken':'wrong'})[0],403)
    self.assertEqual(call(teacher,'setup','POST',{'name':'Teacher','login':'teacher','password':'secure-password','setupToken':'integration-setup-token-2026'})[0],200)
    self.assertEqual(call(stranger,'setup','POST',{'name':'Other','login':'other','password':'secure-password','setupToken':'integration-setup-token-2026'})[0],409)
    self.assertEqual(call(teacher,'classes','POST',{'name':'7 A'},'https://attacker.example')[0],403)
    cl=call(teacher,'classes','POST',{'name':'7 A'})[1][0]
    self.assertEqual(call(student,'join','POST',{'code':cl['code'],'name':'Student One','login':'student','password':'student-password'})[0],200)
    self.assertEqual(call(student,'questions')[0],404)
    self.assertEqual(len(call(student,'rules')[1]),24)
    self.assertEqual(call(client(),'login','POST',{'login':'teacher','password':'secure-password','role':'student'})[0],403)
    self.assertEqual(call(teacher,'classes')[1][0]['student_count'],1)
    bank=call(teacher,'questions')[1]
    self.assertEqual(len(bank['questions']),240)
    q=dict(prompt='She ___ to school.',options=['go','goes','going'],answer=1,unit=bank['units'][0]['id'],level=1,explanation='Use the third-person singular form.')
    added=call(teacher,'questions','POST',q)[1]['questions'][-1]
    aid=call(teacher,'assignments','POST',{'class_id':cl['id'],'title':'Week 1','questions':[added['id']]})[1][0]['id']
    self.assertEqual(call(student,'assignments')[1],[])
    self.assertEqual(call(teacher,'assignments/'+aid,'PUT',{'title':'Week 1 edited','questions':[added['id']]})[0],200)
    self.assertEqual(call(teacher,'assignments/'+aid+'/publish','POST',{})[0],200)
    self.assertEqual(call(teacher,'assignments/'+aid,'PUT',{'title':'Bad edit','questions':[added['id']]})[0],409)
    # Later edits must not rewrite the published task or its answer key.
    q['answer']=0
    self.assertEqual(call(teacher,'questions/'+added['id'],'PUT',q)[0],200)
    a=call(student,'assignments/'+aid+'/start','POST',{})[1]
    self.assertNotIn('answer',a['questions'][0]);self.assertNotIn('explanation',a['questions'][0])
    self.assertEqual(call(stranger,'attempts/'+a['id'],'PUT',{'answers':[1]})[0],401)
    self.assertEqual(call(student,'attempts/'+a['id']+'/submit','PUT',{'answers':[None]})[0],400)
    answer=a['questions'][0]['options'].index('goes')
    self.assertEqual(call(student,'attempts/'+a['id'],'PUT',{'answers':[answer]})[0],200)
    resumed=call(student,'assignments/'+aid+'/start','POST',{})[1]
    self.assertEqual(resumed['id'],a['id']);self.assertEqual(resumed['answers'],[answer])
    result=call(student,'attempts/'+a['id']+'/submit','PUT',{'answers':[answer]})[1]['result']
    self.assertEqual(result['score'],1)
    self.assertEqual(call(student,'attempts/'+a['id']+'/submit','PUT',{'answers':[0]})[0],409)
    self.assertEqual(call(student,'attempts/'+a['id'],'PUT',{'answers':[0]})[0],409)
    self.assertEqual(call(teacher,'results')[1][0]['result']['score'],1)
    self.assertEqual(call(student,'results')[0],404)
    # Another classroom cannot open the assignment or submit this learner's attempt.
    otherclass=call(teacher,'classes','POST',{'name':'7 B'})[1][-1]
    self.assertEqual(call(stranger,'join','POST',{'code':otherclass['code'],'name':'Student Two','login':'student2','password':'student-password2'})[0],200)
    self.assertEqual(call(stranger,'assignments/'+aid+'/start','POST',{})[0],404)
    self.assertEqual(call(stranger,'attempts/'+a['id'],'PUT',{'answers':[0]})[0],404)
    self.assertEqual(call(teacher,'settings','PUT',{'email':'wrong'})[0],400)
    self.assertEqual(call(teacher,'settings','PUT',{'email':'teacher@example.com'})[0],200)
    self.assertEqual(call(teacher,'settings','PUT',{'email':'teacher@example.com\r\nBcc:x@x.com'})[0],400)
    # Mail is queued without configuration and is delivered once configured.
    app.deliver_mail()
    self.assertEqual(call(teacher,'results')[1][0]['email_status'],'waiting')
    class SMTP:
        sent=[]
        def __init__(self,*a,**kw):pass
        def __enter__(self):return self
        def __exit__(self,*a):pass
        def starttls(self):pass
        def send_message(self,m):self.sent.append(m)
    with patch.dict(os.environ,{'SMTP_HOST':'smtp.example.com','SMTP_FROM':'report@example.com'}),patch.object(app.smtplib,'SMTP',SMTP):
        app.deliver_mail();app.deliver_mail()
    self.assertEqual(len(SMTP.sent),1)
    self.assertEqual(SMTP.sent[0]['To'],'teacher@example.com')
    self.assertIn('Score: 1/1',SMTP.sent[0].get_content())
    self.assertEqual(call(teacher,'results')[1][0]['email_status'],'sent')
    self.assertEqual(call(student,'password','PUT',{'current':'wrong','password':'new-password-2026'})[0],403)
    self.assertEqual(call(student,'password','PUT',{'current':'student-password','password':'new-password-2026'})[0],200)
    self.assertEqual(call(student,'logout','POST',{})[0],200)
    self.assertEqual(call(student,'me')[0],401)
    self.assertEqual(call(student,'login','POST',{'login':'student','password':'new-password-2026'})[0],200)
    self.assertEqual(call(student,'assignments')[1][0]['result']['score'],1)
    # Malformed payloads and booleans cannot be accepted as choice indices.
    self.assertEqual(call(teacher,'questions','POST',{**q,'answer':True})[0],400)
    self.assertEqual(call(teacher,'assignments','POST',{'class_id':cl['id'],'title':'Bad','questions':['unknown']})[0],400)
    with app.conn() as c:
        stored=c.execute("SELECT password FROM users WHERE login='student'").fetchone()[0]
        self.assertNotIn('new-password',stored)
        self.assertEqual(c.execute('SELECT count(*) FROM mail').fetchone()[0],1)
    print('PASS: authentication, class boundaries, teacher editing, immutable snapshots, shuffled server grading, autosave, final submission, queued email, password change and persistence.')

if __name__=='__main__':
 try:
  result=unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(ClassroomTest))
  success=result.wasSuccessful()
 finally:server.shutdown();server.server_close();TEMP.cleanup()
 sys.exit(0 if success else 1)
