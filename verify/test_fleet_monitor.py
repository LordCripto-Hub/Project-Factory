import importlib.machinery,importlib.util,json,os,sys,tempfile,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"bin"))
from fleet_monitor import *
class TestFleet(unittest.TestCase):
 def task(self,**x):
  t={"id":"a","state":"working","assignee":"h/main:W","updated":0,"comments":[],"proofs":[],"ownerHistory":[{"action":"assign","agent_id":"h/main:W","ts":0}]};t.update(x);return t
 def owner(self,**x):
  o={"state":"alive","status":"idle","activity_updated_at":0};o.update(x);return o
 def test_states_dedupe_and_close_safety(self):
  self.assertEqual(classify(self.task(state="review",comments=[{"by":"h/main:W","ts":1,"body":"Worker handoff: PASS"}]),self.owner(),1),REVIEW_READY)
  self.assertEqual(classify(self.task(),None,1),STALE)
  self.assertEqual(classify(self.task(state="done"),None,999),BENIGN)
  self.assertEqual((heartbeat_minutes(1),heartbeat_minutes(9)),(2,5))
  self.assertEqual(classify(self.task(),{"state":"alive","status":"working","activity_updated_at":0,"heartbeat_at":998},999),BENIGN)
  self.assertEqual(classify(self.task(),{"state":"alive","status":"working","heartbeat_at":0},999),STALE)
  self.assertEqual(classify(self.task(),{"state":"dead","status":"idle","activity_updated_at":998},999),STALE)
  self.assertEqual(classify(self.task(),{"state":"alive","retired":True,"status":"idle","activity_updated_at":998},999),STALE)
  self.assertEqual(classify(self.task(comments=[{"by":"CEO","ts":999}]),{"state":"alive","status":"idle","activity_updated_at":998,"heartbeat_at":998},999),WAITING)
  with tempfile.TemporaryDirectory() as d:
   l=Ledger(d+"/l.json");t=self.task(state="blocked");first=l.observe(t,self.owner(),"fail",1);self.assertEqual(set(first["pending"]),{"nightwatch","boss"});before=Path(d+"/l.json").read_bytes();retry=l.observe(t,self.owner(),"fail",2);self.assertEqual(set(retry["pending"]),{"nightwatch","boss"});self.assertEqual(Path(d+"/l.json").read_bytes(),before);l.ack("a",first["digest"],"nightwatch");self.assertEqual(l.observe(t,self.owner(),"fail",3)["pending"],["boss"]);l.ack("a",first["digest"],"boss");self.assertIsNone(l.observe(t,self.owner(),"fail",4));self.assertEqual(t["monitorState"],BLOCKED);self.assertEqual(t["monitorAction"],"resolve_blocker")
   t=self.task(state="review",comments=[{"by":"h/main:W","ts":1,"body":"Worker handoff: PASS"}]);o={"state":"alive","status":"idle","heartbeat_at":1}
   review=l.observe(t,o,"worker_handoff",1);self.assertIsNotNone(review);l.ack("a",review["digest"],"nightwatch");l.ack("a",review["digest"],"boss");self.assertIsNone(l.observe(t,o,"card_state",2));self.assertIsNone(l.observe(t,o,"complete",3))
 def test_review_handoff_is_bound_to_current_owner_epoch(self):
  owner={"state":"alive","status":"idle","heartbeat_at":200}
  history=[{"action":"replace","agent_id":"h/main:W","ts":100}]
  old_author=self.task(state="review",ownerHistory=history,comments=[{"by":"h/main:Old","ts":110,"body":"Worker handoff: PASS"}])
  old_epoch=self.task(state="review",ownerHistory=history,comments=[{"by":"h/main:W","ts":90,"body":"Worker handoff: PASS"}])
  current=self.task(state="review",ownerHistory=history,comments=[{"by":"h/main:W","ts":110,"body":"Worker handoff: PASS"}])
  self.assertNotEqual(classify(old_author,owner,201),REVIEW_READY)
  self.assertNotEqual(classify(old_epoch,owner,201),REVIEW_READY)
  self.assertEqual(classify(current,owner,201),REVIEW_READY)
 def test_queue_heartbeat_does_not_fan_out_monitor_requests(self):
  source=(ROOT/"bin"/"queue-client.py").read_text(encoding="utf-8")
  heartbeat=source[source.index("def heartbeat():"):source.index("\ndef execute(")]
  self.assertNotIn("/todo/monitor-event",heartbeat)
 def test_mocked_lifecycle_wake_once_and_retirement_wins(self):
  with tempfile.TemporaryDirectory() as d:
   old=os.environ.copy();os.environ.update({"INSTALL_DIR":d,"QUEUE_SECRET":"test","HOST_ID":"h","BOSS_AGENT":"main:Boss"})
   try:
    loader=importlib.machinery.SourceFileLoader("todo_monitor_mock",str(ROOT/"bin"/"todo-server.py"));spec=importlib.util.spec_from_loader(loader.name,loader);todo=importlib.util.module_from_spec(spec);loader.exec_module(todo)
    todo.BOARD_PATH=d+"/board.json";todo.TODOS_DIR=d;todo.FLEET=Ledger(d+"/end-to-end.json")
    worker=self.owner(agent_id="h/main:W",status="blocked");todo.roster_map=lambda:{"h/main:W":worker}
    board=todo.blank_board();board["tasks"]["a"]=self.task(state="working");board["order"]=["a"];todo.save_board(board,allow_shrink=True)
    calls=[];failed={"boss":True}
    def send(agent,msg,**_kwargs):
     self.assertFalse(todo.STORE_LOCK._is_owned(),"fleet delivery held the board lock")
     calls.append(agent)
     if agent==todo.BOSS_FULL and failed["boss"]:failed["boss"]=False;return 1
     return 0
    todo.mp_send=send
    todo.process_fleet_event("a","fail");self.assertEqual(calls,[todo.NW_AGENT,todo.BOSS_FULL])
    calls.clear();todo.process_fleet_event("a","heartbeat");self.assertEqual(calls,[todo.BOSS_FULL])
    calls.clear();todo.process_fleet_event("a","heartbeat");self.assertEqual(calls,[])
    persisted=todo.load_board()["tasks"]["a"];self.assertEqual((persisted["monitorState"],persisted["monitorAction"]),(BLOCKED,"resolve_blocker"))
    fake=object.__new__(todo.Handler);fake.json=lambda payload,status=200,**_:(status,payload)
    status,payload=todo.Handler.update(fake,"nightwatch",{"op":"add","token":"replayed","text":"x"})
    self.assertEqual((status,payload["error"]),(403,"nightwatch_cannot_create"));self.assertEqual(todo.TOKENS,{})
   finally:
    os.environ.clear();os.environ.update(old);sys.modules.pop("mpcommon",None)
if __name__=='__main__':unittest.main()
