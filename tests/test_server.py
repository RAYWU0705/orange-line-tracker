import os,tempfile,unittest,json,threading,urllib.request,urllib.error
TMP=tempfile.TemporaryDirectory();os.environ['TRACKER_DATA']=TMP.name
import server
class ServerTests(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
  cls.http=server.ThreadingHTTPServer(('127.0.0.1',0),server.Handler);cls.url='http://127.0.0.1:'+str(cls.http.server_port);threading.Thread(target=cls.http.serve_forever,daemon=True).start()
 @classmethod
 def tearDownClass(cls):cls.http.shutdown();cls.http.server_close();TMP.cleanup()
 def req(self,path,data=None,auth=True):
  headers={'Content-Type':'application/json'}
  if auth:headers['Authorization']='Bearer '+server.KEY
  r=urllib.request.Request(self.url+path,headers=headers,data=json.dumps(data).encode() if data is not None else None)
  with urllib.request.urlopen(r) as response:return json.load(response)
 def test_auth(self):
  with self.assertRaises(urllib.error.HTTPError) as c:self.req('/api/state',auth=False)
  self.assertEqual(c.exception.code,401)
 def test_full_workflow(self):
  d={'car':402,'time':server.now().isoformat(),'kind':'service','run':'430','station':'景安','destination':'南勢角','note':'<script>safe</script>'};self.assertEqual(self.req('/api/record',d)['added'],1);self.assertEqual(self.req('/api/record',d)['added'],0)
  s=self.req('/api/state');f=s['fleet'][0];self.assertEqual(f['last']['car'],402);self.assertTrue(f['today']);self.assertEqual(len(s['fleet']),28)
  backup=self.req('/api/export');count=len(backup['records']);self.req('/api/import',backup);self.assertEqual(len(self.req('/api/export')['records']),count)
  self.req('/api/engineering',{'car':401,'start':(server.now()-server.timedelta(days=1)).isoformat(),'state':'施工中','note':'測試工程','source':'測試'})
  f=self.req('/api/state')['fleet'][0];self.assertTrue(f['engineering']['recovered']);self.assertEqual(f['engineering']['state'],'施工中')
  self.req('/api/delete-record',{'id':f['records'][0]['id']});self.assertEqual(len(self.req('/api/export')['records']),0)
 def test_future(self):
  with self.assertRaises(urllib.error.HTTPError):self.req('/api/record',{'car':401,'time':(server.now()+server.timedelta(days=2)).isoformat()})
 def test_bad_settings(self):
  with self.assertRaises(urllib.error.HTTPError):self.req('/api/settings',{'cutoff':19})
 def test_import_atomic(self):
  before=len(self.req('/api/export')['records'])
  with self.assertRaises(urllib.error.HTTPError):self.req('/api/import',{'version':1,'records':[{'car':401,'time':'2026-01-01T12:00:00+08:00'},{'car':500,'time':'2026-01-01T12:00:00+08:00'}]})
  self.assertEqual(len(self.req('/api/export')['records']),before)
 def test_today_coverage(self):
  with self.assertRaises(urllib.error.HTTPError):self.req('/api/coverage',{'day':server.opday(server.now().isoformat()),'value':1})
 def test_static(self):
  with urllib.request.urlopen(self.url+'/') as r:self.assertIn('橘線觀測站',r.read().decode())
