import importlib.machinery,importlib.util,json,os,sys,tempfile,unittest
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
  self.assertEqual(classify(self.task(),{"state":"alive","status":"working","activity_updated_at":998},999),BENIGN)
  self.assertEqual(classify(self.task(),{"state":"alive","status":"working","activity_updated_at":0},999),STALE)
  self.assertEqual(classify(self.task(),{"state":"dead","status":"idle","activity_updated_at":998},999),STALE)
  self.assertEqual(classify(self.task(),{"state":"alive","retired":True,"status":"idle","activity_updated_at":998},999),STALE)
  self.assertEqual(classify(self.task(comments=[{"by":"CEO","ts":999}]),{"state":"alive","status":"idle","activity_updated_at":998},999),WAITING)
  with tempfile.TemporaryDirectory() as d:
   l=Ledger(d+"/l.json");t=self.task(state="blocked");self.assertIsNotNone(l.observe(t,self.owner(),"fail",1));self.assertIsNone(l.observe(t,self.owner(),"fail",2));self.assertEqual(t["monitorState"],BLOCKED);self.assertEqual(t["monitorAction"],"resolve_blocker")
 def test_mocked_lifecycle_wake_once_and_retirement_wins(self):
  with tempfile.TemporaryDirectory() as d:
   old=os.environ.copy();os.environ.update({"INSTALL_DIR":d,"QUEUE_SECRET":"test","HOST_ID":"h","BOSS_AGENT":"main:Boss"})
   try:
    loader=importlib.machinery.SourceFileLoader("todo_monitor_mock",str(Path(__file__).resolve().parents[1]/"bin"/"todo-server.py"));spec=importlib.util.spec_from_loader(loader.name,loader);todo=importlib.util.module_from_spec(spec);loader.exec_module(todo)
    sent=[];todo.mp_send=lambda *args,**kwargs:sent.append(args) or 0
    worker=self.owner(agent_id="h/main:W",status="blocked");todo.roster_map=lambda:{"h/main:W":worker}
    t=self.task(state="working");todo.observe_fleet(t,"fail");todo.observe_fleet(t,"fail")
    self.assertEqual((t["monitorState"],t["monitorAction"]),(BLOCKED,"resolve_blocker"));self.assertEqual(len(sent),2) # Nightwatch + Boss, once each
    t["state"]="done";todo.observe_fleet(t,"stop");self.assertEqual(t["monitorState"],BENIGN);self.assertEqual(len(sent),2)
    fake=object.__new__(todo.Handler);fake.json=lambda payload,status=200,**_:(status,payload)
    status,payload=todo.Handler.update(fake,"nightwatch",{"op":"add","token":"replayed","text":"x"})
    self.assertEqual((status,payload["error"]),(403,"nightwatch_cannot_create"));self.assertEqual(todo.TOKENS,{})
   finally:
    os.environ.clear();os.environ.update(old);sys.modules.pop("mpcommon",None)
if __name__=='__main__':unittest.main()
