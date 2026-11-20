import copy,json,tempfile,unittest
from pathlib import Path
from lex import Engine,Rejected

def bundle(engine):
 s=engine.view();c={'source':'S1','locator':'L2'}
 red={'target':'R2','failed_link':'Email report does not establish signed acceptance','citation':{'source':'S1','locator':'L3'},'consequence':'Timing remains unverified','resolution_test':'Obtain signed acceptance record'}
 return {'matter':'DEMO','stream':'litigation-disclosure','snapshot':{k:{'hash':v['hash'],'version':v['version']} for k,v in s['sources'].items()},'preparation':{'evidence':'Email reports acceptance; signed record missing','issues':'Acceptance timing remains unverified','candidate_draft':'Acceptance preceded dispatch.','citations':[c]},'red':red,'blue':{'original_objection':copy.deepcopy(red),'action':'narrow','before':'Acceptance preceded dispatch.','after':'The email reports acceptance before dispatch; signed acceptance is missing.','citations':[c,{'source':'S1','locator':'L3'}]},'purple':{'original_objection':copy.deepcopy(red),'result':'resolved-within-scope','scope':'Attribution only','evidence_gap':'open','rationale':'Wording repair preserves the missing-record gap'},'gold':{'options':['Request signed record','Use attributed account for review'],'residual_risks':['Acceptance remains unverified']}}
class ReviewImportTests(unittest.TestCase):
 def setUp(self):self.t=tempfile.TemporaryDirectory();self.e=Engine(self.t.name);self.e.demo(0)
 def tearDown(self):self.e.db.close();self.t.cleanup()
 def test_import_assemble(self):
  self.e.import_review(1,bundle(self.e));self.e.assemble(2);s=self.e.view();self.assertEqual(s['packages'][0]['status'],'prepared');self.assertFalse(s['runs'][0]['release_authority']);self.assertEqual(s['objections'][0]['evidence_gap'],'open')
 def test_forged_objection_atomic(self):
  b=bundle(self.e);b['blue']['original_objection']['consequence']='No problem'
  with self.assertRaises(Rejected):self.e.import_review(1,b)
  self.assertEqual(self.e.view()['version'],1);self.assertEqual(self.e.view()['runs'],[])
 def test_gap_closure(self):
  b=bundle(self.e);b['purple']['evidence_gap']='closed'
  with self.assertRaises(Rejected):self.e.import_review(1,b)
 def test_missing_snapshot_source(self):
  b=bundle(self.e);del b['snapshot']['S2']
  with self.assertRaises(Rejected):self.e.import_review(1,b)
 def test_scope_injection(self):
  for mutate in [lambda b:b.update(matter='OTHER'),lambda b:b.update(stream='negotiation'),lambda b:b.update(approved=True),lambda b:b['blue'].update(classification='sealed')]:
   b=bundle(self.e);mutate(b)
   with self.assertRaises(Rejected):self.e.import_review(1,b)
 def test_missing_citation(self):
  b=bundle(self.e);b['blue']['citations'][0]['locator']='L90'
  with self.assertRaises(Rejected):self.e.import_review(1,b)
 def test_hold_blocks_assembly(self):
  b=bundle(self.e);b['purple']['result']='hold';self.e.import_review(1,b)
  with self.assertRaises(Rejected):self.e.assemble(2)
 def test_changed_snapshot_blocks_reassembly(self):
  self.e.import_review(1,bundle(self.e));self.e.change_source(2,'S1')
  with self.assertRaises(Rejected):self.e.assemble(3)
 def test_policy_version_and_budget(self):
  self.e.import_review(1,bundle(self.e));self.e.assemble(2);self.e.configure_policy(3,{'labels':['Traceability','Review','Human approval'],'max_cycles':1});s=self.e.view();self.assertEqual(s['policy']['version'],2);self.assertEqual(len(s['policy_history']),1);self.assertTrue(s['packages'][0]['stale'])
  with self.assertRaises(Rejected):self.e.import_review(4,bundle(self.e))
 def test_invalid_policy(self):
  for policy in [{'labels':['a'],'max_cycles':3},{'labels':['a','b','c'],'max_cycles':True},{'labels':['a','b','c'],'max_cycles':11}]:
   with self.assertRaises(Rejected):self.e.configure_policy(1,policy)
