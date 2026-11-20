"""LEX local review engine. Standard library only; no model or dispatch integration."""
import argparse, hashlib, html, io, json, secrets, sqlite3, threading, zipfile
from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

APP_VERSION = '0.3.1'
KINDS = ('chronology','claims','evidence','contradictions','risks','drafting','decisions')
STREAMS = ('litigation-disclosure','data-access','negotiation')
def digest(b): return hashlib.sha256(b).hexdigest()
def encode(v): return json.dumps(v, sort_keys=True, ensure_ascii=False)
class Rejected(ValueError): pass
class Engine:
    def __init__(self, root):
        self.root=Path(root).resolve(); self.root.mkdir(parents=True,exist_ok=True)
        (self.root/'originals').mkdir(exist_ok=True); (self.root/'exports').mkdir(exist_ok=True)
        self.lock=threading.RLock()
        self.db=sqlite3.connect(self.root/'lex.sqlite3',check_same_thread=False)
        self.db.execute('CREATE TABLE IF NOT EXISTS state (id INTEGER PRIMARY KEY CHECK(id=1), version INTEGER, body TEXT)')
        if not self.db.execute('SELECT 1 FROM state').fetchone():
            self.db.execute('INSERT INTO state VALUES(1,0,?)',(encode({'sources':{},'records':[], 'objections':[], 'runs':[], 'packages':[], 'audit':[], 'policy':{'version':1,'labels':['Source traceability','Objection review','Human package review'],'illustrative':True}}),)); self.db.commit()
        self.migrate_review_policies()
    def migrate_review_policies(self):
        v,s=self.load()
        if not any('policy_version' not in r for r in s['runs']):return
        policy=1;versions=[]
        for event in s['audit']:
            if event['action']=='Revise illustrative review policy':policy+=1
            if event['action'] in ('Import validated review proposals','Simulate Preparation → Red → Blue → Purple → Gold'):versions.append(policy)
        if len(versions)!=len(s['runs']):return
        def migrate(state):
            for run,version in zip(state['runs'],versions):run.setdefault('policy_version',version)
        self.mutate(v,'Recover review policy provenance from audit; approvals unchanged',migrate)
    def load(self):
        with self.lock:
            v,b=self.db.execute('SELECT version,body FROM state').fetchone(); return v,json.loads(b)
    def mutate(self, expected, action, fn):
        with self.lock:
            self.db.execute('BEGIN IMMEDIATE')
            try:
                v,s=self.load()
                if expected!=v: raise Rejected('Conflicting version; refresh and retry')
                result=fn(s)
                s['audit'].append({'version':v+1,'action':action,'mode':'local prototype'})
                self.db.execute('UPDATE state SET version=?,body=? WHERE id=1',(v+1,encode(s))); self.db.commit()
                return result
            except Exception: self.db.rollback(); raise
    def source(self,s,matter,sid,locator=None):
        src=s['sources'].get(sid)
        if not src or src['matter']!=matter: raise Rejected('Missing source or cross-matter access')
        p=self.root/'originals'/src['hash']
        if not p.is_file() or digest(p.read_bytes())!=src['hash']: raise Rejected('Original integrity failure')
        if locator is not None and locator not in src['locators']: raise Rejected('Missing locator')
        return src
    def cite(self,s,matter,c):
        if set(c)!= {'source','locator'}: raise Rejected('Citation requires source and locator')
        return self.source(s,matter,c['source'],c['locator'])
    def ingest_into(self,s,matter,name,text,parent=None):
        if not all(isinstance(x,str) and x.strip() for x in (matter,name,text)): raise Rejected('Required source fields')
        raw=text.encode(); h=digest(raw)
        for sid,src in s['sources'].items():
            if src['matter']==matter and src['hash']==h: return sid
        if parent: self.source(s,matter,parent)
        p=self.root/'originals'/h
        if not p.exists(): p.write_bytes(raw); p.chmod(0o400)
        sid='S'+str(len(s['sources'])+1)
        s['sources'][sid]={'id':sid,'matter':matter,'name':name,'hash':h,'version':1,'parent':parent,'family':s['sources'][parent]['family'] if parent else sid,'locators':{'L'+str(i+1):line for i,line in enumerate(text.splitlines())},'derivative':{'kind':'UTF-8 line extraction','original_hash':h},'classification':'ordinary'}
        return sid
    def record_into(self,s,r):
        if r.get('kind') not in KINDS or r.get('stream') not in STREAMS: raise Rejected('Invalid record kind or workstream')
        if r.get('status') not in ('allegation','inference','disputed','unknown','attributed'): raise Rejected('Invalid assertion status')
        if not r.get('text') or not r.get('matter'): raise Rejected('Missing record text/matter')
        if r.get('classification','ordinary')!='ordinary': raise Rejected('Sealed records are not accepted by this prototype')
        if r['status']!='unknown' and not r.get('citations'): raise Rejected('Unsupported assertion requires unknown status')
        for c in r.get('citations',[]): self.cite(s,r['matter'],c)
        r=dict(r,id='R'+str(len(s['records'])+1),version=1,classification='ordinary'); s['records'].append(r); return r['id']
    def demo(self,expected):
        def run(s):
            if s['sources']: raise Rejected('Demo already initialized')
            a=self.ingest_into(s,'DEMO','Fictional email.txt','FICTIONAL training example.\nSender reports acceptance before dispatch.\nSigned acceptance record is not attached.')
            b=self.ingest_into(s,'DEMO','Dispatch export.txt','FICTIONAL training example.\nDispatch recorded at 14:00 on 2030-04-03.')
            texts=['2030-04-03: export records dispatch at 14:00.','Email reports acceptance before dispatch; acceptance itself is unverified.','Email and dispatch export are distinct source families.','Acceptance timing cannot be compared without the signed record.','Missing signed acceptance record; do not infer completion.','Prepare an attributed account with the evidence gap visible.','Historical HOLD is superseded only for attributed drafting scope; prepared, not filed or served.']
            for k,t in zip(KINDS,texts): self.record_into(s,{'matter':'DEMO','kind':k,'stream':STREAMS[0],'text':t,'status':'attributed' if k in ('chronology','claims') else 'unknown','citations':[{'source':b if k=='chronology' else a,'locator':'L2'}]})
        self.mutate(expected,'Initialize fictional case',run)
    def cycle_count(self,s):
        return sum(r.get('session',1)==s.get('review_session',1) for r in s['runs'])
    def new_session(self,expected,reason):
        if not isinstance(reason,str) or not reason.strip() or len(reason)>500: raise Rejected('A reason for another review session is required')
        def run(s):
            s['review_session']=s.get('review_session',1)+1
            s.setdefault('session_history',[]).append({'session':s['review_session'],'reason':reason})
        self.mutate(expected,'Start review session: '+reason,run)
    def simulate(self,expected):
        def run(s):
            if not s['sources']: raise Rejected('Initialize demo first')
            if self.cycle_count(s)>=s['policy'].get('max_cycles',3): raise Rejected('Cycle limit exhausted; human decision required')
            for sid in s['sources']: self.source(s,'DEMO',sid)
            oid='O'+str(len(s['objections'])+1)
            obj={'id':oid,'matter':'DEMO','target':'R2','failed_link':'Reported acceptance is not signed acceptance','citation':{'source':'S1','locator':'L3'},'consequence':'Cannot verify timing','test':'Obtain signed acceptance and compare its timestamp','evidence_gap':'open','status':'resolved-within-scope','scope':'attributed wording only','repair':{'action':'narrow','before':'Acceptance preceded dispatch.','after':'An email reports acceptance before dispatch. The signed acceptance record is missing.'},'purple':'Wording repaired; evidence gap remains open.'}
            s['objections'].append(obj)
            s['runs'].append({'policy_version':s['policy']['version'],'session':s.get('review_session',1),'mode':'SIMULATION — fixed synthetic outputs, no AI call','snapshot':{k:v['version'] for k,v in s['sources'].items()},'preparation':{'evidence':'S1 L2–L3; S2 L2','issues':'Acceptance timing unverified','candidate':'Acceptance preceded dispatch.'},'red':oid,'blue':obj['repair'],'purple':obj['purple'],'gold':['Request missing record','Use attributed wording for internal review'],'release_authority':False})
        self.mutate(expected,'Simulate Preparation → Red → Blue → Purple → Gold',run)
    def validate_snapshot(self,s,snapshot):
        current={sid:{'hash':src['hash'],'version':src['version']} for sid,src in s['sources'].items() if src['matter']=='DEMO'}
        if not current or snapshot!=current: raise Rejected('Complete current evidence snapshot required')
        for sid in current: self.source(s,'DEMO',sid)
    def import_review(self,expected,bundle,origin=None):
        """Accept a structurally validated proposal bundle, never a truth or release verdict."""
        def run(s):
            def fields(obj,keys):
                if not isinstance(obj,dict) or set(obj)!=set(keys.split()): raise Rejected('Unexpected or missing review fields: '+keys)
            def text(value):
                if not isinstance(value,str) or not value.strip() or len(value)>20000: raise Rejected('Review text must be non-empty and bounded')
            def citations(value):
                if not isinstance(value,list) or not value or len(value)>100: raise Rejected('Review citations required')
                for c in value: self.cite(s,'DEMO',c)
            fields(bundle,'matter stream snapshot preparation red blue purple gold')
            if bundle['matter']!='DEMO' or bundle['stream']!=STREAMS[0]: raise Rejected('Review is scoped to fictional litigation-disclosure')
            self.validate_snapshot(s,bundle['snapshot'])
            if self.cycle_count(s)>=s['policy'].get('max_cycles',3): raise Rejected('Cycle limit exhausted; human decision required')
            prep,red,blue,purple,gold=(bundle[k] for k in ('preparation','red','blue','purple','gold'))
            fields(prep,'evidence issues candidate_draft citations');fields(red,'target failed_link citation consequence resolution_test');fields(blue,'original_objection action before after citations');fields(purple,'original_objection result scope evidence_gap rationale');fields(gold,'options residual_risks')
            for key in ('evidence','issues','candidate_draft'):text(prep[key])
            citations(prep['citations'])
            if red['target'] not in {r['id'] for r in s['records'] if r['matter']=='DEMO' and r['stream']==STREAMS[0]}: raise Rejected('Unknown or out-of-scope objection target')
            for key in ('failed_link','consequence','resolution_test'):text(red[key])
            self.cite(s,'DEMO',red['citation'])
            if blue['original_objection']!=red or purple['original_objection']!=red: raise Rejected('Original Red objection must be preserved unchanged')
            if blue['action'] not in ('support','correct','narrow','withdraw') or blue['before']!=prep['candidate_draft']: raise Rejected('Repair must address the exact candidate draft')
            text(blue['after']);citations(blue['citations'])
            if purple['result'] not in ('resolved-within-scope','unresolved','needs-evidence','hold'): raise Rejected('Invalid Purple disposition')
            if purple['evidence_gap']!='open': raise Rejected('Fictional signed-record gap remains open; acquisition workflow required to close it')
            text(purple['scope']);text(purple['rationale'])
            for key in ('options','residual_risks'):
                if not isinstance(gold[key],list) or not 1<=len(gold[key])<=10: raise Rejected('Gold requires options and residual risks')
                for item in gold[key]:text(item)
            oid='O'+str(len(s['objections'])+1)
            s['objections'].append(dict(id=oid,matter='DEMO',target=red['target'],failed_link=red['failed_link'],citation=red['citation'],consequence=red['consequence'],test=red['resolution_test'],evidence_gap='open',status=purple['result'],scope=purple['scope'],repair=blue,purple=purple['rationale']))
            s['runs'].append({'policy_version':s['policy']['version'],'session':s.get('review_session',1),'mode':origin or 'IMPORTED PROPOSALS — structural checks only; reasoning not independently verified','snapshot':bundle['snapshot'],'preparation':prep,'red':oid,'blue':blue,'purple':purple,'gold':gold,'release_authority':False,'bundle_digest':digest(encode(bundle).encode())})
            # A new successful review does not change an already reviewed artifact.
            # A newly unresolved objection does invalidate packages that include its target.
            if purple['result']!='resolved-within-scope':
                for p in s['packages']:
                    if red['target'] in p['record_versions']:
                        p['stale']=True;p['approval']=None;p['stale_reason']='Unresolved objection '+oid
        self.mutate(expected,'Import validated review proposals',run)
    def configure_policy(self,expected,policy):
        def run(s):
            if not isinstance(policy,dict) or set(policy)!={'labels','max_cycles'}: raise Rejected('Policy requires labels and max_cycles')
            labels=policy['labels'];budget=policy['max_cycles']
            if not isinstance(labels,list) or len(labels)!=3 or any(not isinstance(x,str) or not x.strip() or len(x)>120 for x in labels): raise Rejected('Provide three bounded illustrative gate labels')
            if type(budget) is not int or not 1<=budget<=10: raise Rejected('Cycle budget must be 1–10')
            if labels==s['policy']['labels'] and budget==s['policy'].get('max_cycles',3):return
            s.setdefault('policy_history',[]).append(s['policy'])
            s['policy']={'version':s['policy']['version']+1,'labels':labels,'max_cycles':budget,'illustrative':True}
            for p in s['packages']:p['stale']=True;p['approval']=None
        self.mutate(expected,'Revise illustrative review policy',run)
    def retest(self,expected,oid,status,close_gap=False):
        def run(s):
            o=next((o for o in s['objections'] if o['id']==oid),None)
            if not o or status not in ('resolved-within-scope','unresolved','needs-evidence','hold'): raise Rejected('Invalid objection/status')
            if close_gap: raise Rejected('Wording repair cannot close evidence gap; acquisition workflow not implemented')
            o['status']=status
            if status!='resolved-within-scope':
                for p in s['packages']:
                    if o['target'] in p['record_versions']:p['stale']=True;p['approval']=None;p['stale_reason']='Unresolved objection '+oid
        self.mutate(expected,'Retest objection',run)
    def assemble(self,expected):
        def run(s):
            if not s['runs']: raise Rejected('Review cycle required')
            if any(o['status']!='resolved-within-scope' for o in s['objections']): raise Rejected('Unrepaired objection')
            rs=[r for r in s['records'] if r['matter']=='DEMO' and r['stream']==STREAMS[0]]
            if any(r['classification']!='ordinary' for r in rs): raise Rejected('Sealed leakage blocked')
            latest=s['runs'][-1]
            manifest={}
            for sid,item in latest['snapshot'].items():
                src=self.source(s,'DEMO',sid)
                expected_version=item['version'] if isinstance(item,dict) else item
                if src['version']!=expected_version or (isinstance(item,dict) and src['hash']!=item['hash']): raise Rejected('Review snapshot changed; rerun review before assembly')
                manifest[sid]={'hash':src['hash'],'version':src['version']}
            for r in rs:
                for c in r['citations']:
                    src=self.cite(s,'DEMO',c); manifest[src['id']]={'hash':src['hash'],'version':src['version']}
            content=['<h1>LEX · EXCALIBUR review packet</h1><p>FICTIONAL • Internal review only • Prepared, not filed, issued or served.</p>','<h2>Draft</h2><p>'+html.escape(s['runs'][-1]['blue']['after'])+'</p>']
            for r in rs: content.append('<h2>'+html.escape(r['kind'])+'</h2><p>'+html.escape(r['text'])+'</p><p>'+html.escape(encode(r['citations']))+'</p>')
            content.append('<h2>Evidence schedule and exhibits</h2>')
            for sid in manifest:
                src=self.source(s,'DEMO',sid); content.append('<h3>'+html.escape(sid+' '+src['name'])+'</h3><pre>'+html.escape(encode(src['locators']))+'</pre>')
            content.append('<h2>Review findings</h2>')
            for o in s['objections']:content.append('<p>'+html.escape(o['id']+' · '+o['status']+' · '+o['scope']+' · '+o['purple'])+'</p>')
            content.append('<h2>Residual risks</h2><p>Signed acceptance record missing. Scope passes do not resolve this evidence gap.</p>')
            gold=latest['gold']
            if isinstance(gold,dict):
                for risk in gold['residual_risks']:content.append('<p>'+html.escape(risk)+'</p>')
            raw=('<!doctype html><meta charset="utf-8"><title>LEX review packet</title><style>body{font:16px system-ui;max-width:850px;margin:48px auto;padding:24px;line-height:1.6}pre{white-space:pre-wrap}h1,h2{color:#175d49}</style>'+''.join(content)).encode()
            h=digest(raw)
            for existing in s['packages']:
                if existing['digest']==h and existing['manifest']==manifest and existing['policy_version']==s['policy']['version']:
                    try:self.verify_package(s,existing)
                    except Rejected:continue
                    return existing['id']
            (self.root/'exports'/(h+'.html')).write_bytes(raw)
            p={'id':'P'+str(len(s['packages'])+1),'digest':h,'manifest':manifest,'record_versions':{r['id']:r['version'] for r in rs},'policy_version':s['policy']['version'],'recipient':'local human reviewer','purpose':'fictional internal review','action':'review-only','approval_version':0,'status':'prepared','filed':False,'served':False,'stale':False,'reviewed':False,'approval':None}
            s['packages'].append(p); return p['id']
        return self.mutate(expected,'Assemble exact review package',run)
    def verify_package(self,s,p):
        path=self.root/'exports'/(p['digest']+'.html')
        if p['stale'] or not path.exists() or digest(path.read_bytes())!=p['digest']: raise Rejected('Stale or altered package')
        if p['policy_version']!=s['policy']['version']: raise Rejected('Review policy changed')
        for sid,m in p['manifest'].items():
            src=self.source(s,'DEMO',sid)
            if m!={'hash':src['hash'],'version':src['version']}: raise Rejected('Changed package dependency')
    def approve(self,expected,pid,h,reviewed=False):
        def run(s):
            p=next((p for p in s['packages'] if p['id']==pid),None)
            if not p or p['digest']!=h: raise Rejected('Exact package digest required')
            self.verify_package(s,p)
            if reviewed:
                if not p['reviewed']:p['reviewed']=True;p['status']='reviewed'
                return
            if not p['reviewed']: raise Rejected('Review rendered package first')
            if p['status']=='approved' and p['approval']:return
            p['approval_version']+=1; p['status']='approved'
            p['approval']={k:p[k] for k in ('digest','manifest','recipient','purpose','action','approval_version','policy_version')}
        self.mutate(expected,'Human review acknowledgement' if reviewed else 'Approve exact review-only package',run)
    def change_source(self,expected,sid):
        def run(s):
            src=self.source(s,'DEMO',sid); src['version']+=1
            for p in s['packages']:
                if sid in p['manifest']: p['stale']=True; p['approval']=None
        self.mutate(expected,'Source metadata revision; dependent packages stale',run)
    def package_zip(self,pid):
        s=self.view();p=next((p for p in s['packages'] if p['id']==pid),None)
        if not p:raise Rejected('Package not found')
        self.verify_package(s,p)
        buffer=io.BytesIO()
        with zipfile.ZipFile(buffer,'w',zipfile.ZIP_DEFLATED) as z:
            z.writestr('review-packet.html',(self.root/'exports'/(p['digest']+'.html')).read_bytes())
            z.writestr('manifest.json',encode(p))
            z.writestr('README.txt','FICTIONAL REVIEW ONLY. Not filed or served. Approval applies only to the exact HTML digest and use in manifest.json. ZIP itself is a transport container, not a separately approved artifact.')
            for sid,metadata in p['manifest'].items():z.writestr('originals/'+sid+'.txt',(self.root/'originals'/metadata['hash']).read_bytes())
        return buffer.getvalue()
    def view(self):
        v,s=self.load(); s['version']=v; s['cycles_used']=self.cycle_count(s)
        for p in s['packages']:
            try: self.verify_package(s,p)
            except Rejected: p['stale']=True; p['approval']=None
        return s

class Handler(BaseHTTPRequestHandler):
    def send(self,body,typ='application/json',status=200,filename=None):
        raw=body if isinstance(body,bytes) else encode(body).encode()
        self.send_response(status)
        if filename:self.send_header('Content-Disposition','attachment; filename="'+filename+'"')
        self.send_header('Content-Type',typ); self.send_header('Content-Length',str(len(raw))); self.send_header('Cache-Control','no-store'); self.send_header('X-Content-Type-Options','nosniff'); self.send_header('Content-Security-Policy',"default-src 'self'; style-src 'self' 'unsafe-inline'; frame-ancestors 'none'; base-uri 'none'"); self.end_headers(); self.wfile.write(raw)
    def valid_host(self): return self.headers.get('Host')==f'127.0.0.1:{self.server.server_port}'
    def do_GET(self):
        if not self.valid_host(): return self.send({'error':'Invalid host'},status=403)
        path=urlparse(self.path).path
        if path=='/api/state':
            state = self.server.engine.view()
            state['app_version'] = APP_VERSION
            return self.send(dict(state,csrf=self.server.token))
        if path.startswith('/download/'):
            try:
                pid=path.removeprefix('/download/')
                return self.send(self.server.engine.package_zip(pid),'application/zip',filename='LEX-'+pid+'.zip')
            except Rejected as ex:return self.send({'error':str(ex)},status=409)
        if path.startswith('/packet/'):
            pid=path.removeprefix('/packet/'); s=self.server.engine.view(); p=next((p for p in s['packages'] if p['id']==pid),None)
            if p:
                file=self.server.engine.root/'exports'/(p['digest']+'.html')
                if not file.is_file(): return self.send({'error':'Package file missing'},status=404)
                raw=file.read_bytes()
                if digest(raw)!=p['digest']: return self.send({'error':'Altered package blocked'},status=409)
                return self.send(raw,'text/html; charset=utf-8')
        files={'/':'index.html','/app.js':'app.js','/style.css':'style.css'}
        if path in files: return self.send((Path(__file__).parent/'static'/files[path]).read_bytes(),{'/':'text/html; charset=utf-8','/app.js':'text/javascript','/style.css':'text/css'}[path])
        self.send({'error':'Not found'},status=404)
    def do_POST(self):
        if not self.valid_host() or self.headers.get('X-LEX-Token')!=self.server.token or self.headers.get('Origin') not in (None,f'http://127.0.0.1:{self.server.server_port}'): return self.send({'error':'Forbidden'},status=403)
        try:
            n=int(self.headers.get('Content-Length','0'))
            if n>100000: raise Rejected('Payload too large')
            b=json.loads(self.rfile.read(n)); e=self.server.engine; v=b['version']; path=urlparse(self.path).path
            if path=='/api/demo': e.demo(v)
            elif path=='/api/new-session': e.new_session(v,b['reason'])
            elif path=='/api/simulate': e.simulate(v)
            elif path=='/api/assemble': e.assemble(v)
            elif path in ('/api/review','/api/approve'): e.approve(v,b['id'],b['digest'],path.endswith('review'))
            elif path=='/api/change': e.change_source(v,b['id'])
            elif path=='/api/policy': e.configure_policy(v,b['policy'])
            elif path=='/api/import-review': e.import_review(v,b['bundle'])
            elif path=='/api/record': e.mutate(v,'Accept validated record proposal',lambda s:e.record_into(s,b['record']))
            else: raise Rejected('Unknown action; dispatch is unavailable')
            self.send({'ok':True})
        except (Rejected,ValueError,KeyError,TypeError) as ex: self.send({'error':str(ex)},status=400)
    def log_message(self,*args): pass

def main():
    p=argparse.ArgumentParser(); p.add_argument('--data',default=str(Path(__file__).parent/'data')); p.add_argument('--port',type=int,default=8765); p.add_argument('--snapshot',action='store_true'); args=p.parse_args()
    e=Engine(args.data)
    if args.snapshot: print(encode(e.view())); return
    server=ThreadingHTTPServer(('127.0.0.1',args.port),Handler); server.engine=e; server.token=secrets.token_urlsafe(32)
    print(f'LEX ready: http://127.0.0.1:{server.server_port} — fictional evidence demo',flush=True)
    try: server.serve_forever()
    except KeyboardInterrupt: server.server_close()
if __name__=='__main__': main()
