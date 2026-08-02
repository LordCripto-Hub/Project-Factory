import sys,tempfile,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"bin"))
from fleet_monitor import *
class TestFleet(unittest.TestCase):
 def task(self,**x):
  t={"id":"a","state":"working","assignee":"h/main:W","updated":0,"comments":[],"proofs":[]};t.update(x);return t
 def owner(self,**x):
  o={"state":"alive","status":"idle","activity_updated_at":0};o.update(x);return o
 def test_states_dedupe_and_close_safety(self):
  self.assertEqual(classify(self.task(state="review",comments=[{"body":"Worker handoff: PASS"}]),self.owner(),1),REVIEW_READY)
  self.assertEqual(classify(self.task(),None,1),STALE)
  self.assertEqual(classify(self.task(state="done"),None,999),BENIGN)
  self.assertEqual((heartbeat_minutes(1),heartbeat_minutes(9)),(2,5))
  with tempfile.TemporaryDirectory() as d:
   l=Ledger(d+"/l.json");t=self.task(state="blocked");self.assertIsNotNone(l.observe(t,self.owner(),"fail",1));self.assertIsNone(l.observe(t,self.owner(),"fail",2));self.assertEqual(t["monitorState"],BLOCKED);self.assertEqual(t["monitorAction"],"resolve_blocker")
if __name__=='__main__':unittest.main()
