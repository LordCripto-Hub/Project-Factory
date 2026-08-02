"""Advisory, durable fleet-monitor reducer; it never owns card lifecycle."""
from __future__ import annotations
import fcntl, hashlib, json, os, re, tempfile, time

REVIEW_READY="review_ready"; BLOCKED="blocked"; WAITING="waiting_instruction"; BENIGN="benign_idle"; STALE="stale"
TERMINAL={"done","cancelled"}
def heartbeat_minutes(value=None):
    try:v=float(os.environ.get("FLEET_MONITOR_HEARTBEAT_MIN","3") if value is None else value)
    except (TypeError,ValueError):v=3
    return min(5,max(2,v))
def context(task,owner):
    handoff=next((c for c in reversed(task.get("comments",[])) if str(c.get("body","")).startswith("Worker handoff")),{})
    text=str(handoff.get("body",""))
    commit=re.search(r"\b[0-9a-f]{40}\b",text,re.I)
    return {"card":task.get("state",""),"owner":task.get("assignee",""),"ownerState":(owner or {}).get("status") or (owner or {}).get("state","missing"),"handoff":bool(handoff),"commit":commit.group(0) if commit else "","tests":"passed" if re.search(r"\b(?:OK|PASS|passed)\b",text,re.I) else "","proofs":len(task.get("proofs",[]))}
def classify(task,owner,now=None):
    now=time.time() if now is None else now;c=context(task,owner)
    if task.get("state") in TERMINAL or task.get("ownerNeedsReplacement"):return BENIGN
    if task.get("state")=="review" and c["handoff"]:return REVIEW_READY
    if task.get("state")=="blocked" or c["ownerState"]=="blocked":return BLOCKED
    if not task.get("assignee") or c["ownerState"] in {"missing","dead","retired"}:return STALE
    if c["ownerState"] in {"starting","working"}:return BENIGN
    active=float((owner or {}).get("activity_updated_at") or (owner or {}).get("timestamp") or task.get("updated") or now)
    if now-active>=heartbeat_minutes()*60:return STALE
    last=(task.get("comments") or [{}])[-1]
    if c["ownerState"]=="idle" and last.get("by")=="CEO" and float(last.get("ts",0))>=active:return WAITING
    return BENIGN
def action(state):return {REVIEW_READY:"verify_handoff",BLOCKED:"resolve_blocker",WAITING:"send_owner_instruction",STALE:"inspect_and_revive_or_replace",BENIGN:"no_action"}[state]
class Ledger:
 def __init__(self,path):self.path=path
 def observe(self,task,owner,event,now=None):
  now=time.time() if now is None else now; state=classify(task,owner,now); ctx=context(task,owner); payload={"event":event,"state":state,"context":ctx}; digest=hashlib.sha256(json.dumps(payload,sort_keys=True).encode()).hexdigest();os.makedirs(os.path.dirname(self.path),exist_ok=True)
  with open(self.path+".lock","a+") as lock:
   fcntl.flock(lock,fcntl.LOCK_EX)
   try:
    with open(self.path,encoding="utf-8") as source:data=json.load(source)
   except (OSError,ValueError):data={}
   prior=data.get(task["id"],{});data[task["id"]]={"digest":digest,"state":state,"updated":now}
   fd,tmp=tempfile.mkstemp(dir=os.path.dirname(self.path),prefix=".fleet-");
   with os.fdopen(fd,"w") as f:json.dump(data,f,sort_keys=True);f.flush();os.fsync(f.fileno())
   os.replace(tmp,self.path)
  task["monitorState"]=state;task["monitorUpdated"]=now;task["monitorAction"]=action(state)
  return None if prior.get("digest")==digest or state==BENIGN else {**payload,"task_id":task["id"],"boss_action":action(state)}
def message(o):
 c=o["context"];return f"[fleet-monitor] event={o['event']} card={o['task_id']} state={o['state']} owner={c['owner']} handoff={c['handoff']} commit={c['commit']} tests={c['tests']} boss_action={o['boss_action']}"
