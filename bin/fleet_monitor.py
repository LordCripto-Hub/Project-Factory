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
    assignee=str(task.get("assignee") or "")
    owner_events=[float(e.get("ts",0)) for e in task.get("ownerHistory",[]) if e.get("agent_id")==assignee and e.get("action") in {"assign","replace","reopen","migrated_existing_owner"}]
    owner_epoch=max(owner_events) if owner_events else float("inf")
    handoff=next((c for c in reversed(task.get("comments",[])) if c.get("by")==assignee and float(c.get("ts",0))>=owner_epoch and str(c.get("body","")).startswith("Worker handoff")),{})
    text=str(handoff.get("body",""))
    commit=re.search(r"\b[0-9a-f]{40}\b",text,re.I)
    return {"card":task.get("state",""),"owner":task.get("assignee",""),"ownerState":(owner or {}).get("status") or (owner or {}).get("state","missing"),"handoff":bool(handoff),"commit":commit.group(0) if commit else "","tests":"passed" if re.search(r"\b(?:OK|PASS|passed)\b",text,re.I) else "","proofs":len(task.get("proofs",[]))}
def classify(task,owner,now=None):
    now=time.time() if now is None else now;c=context(task,owner)
    if task.get("state") in TERMINAL or task.get("ownerNeedsReplacement"):return BENIGN
    if not task.get("assignee") or (owner or {}).get("state") in {"missing","dead","retired"} or (owner or {}).get("retired") is True:return STALE
    if task.get("state")=="review" and c["handoff"]:return REVIEW_READY
    if task.get("state")=="blocked" or c["ownerState"]=="blocked":return BLOCKED
    raw_active=(owner or {}).get("heartbeat_at")
    if raw_active is None:return STALE
    active=float(raw_active)
    if now-active>=heartbeat_minutes()*60:return STALE
    last=(task.get("comments") or [{}])[-1]
    if c["ownerState"]=="idle" and last.get("by")=="CEO" and float(last.get("ts",0))>=active:return WAITING
    return BENIGN
def action(state):return {REVIEW_READY:"verify_handoff",BLOCKED:"resolve_blocker",WAITING:"send_owner_instruction",STALE:"inspect_and_revive_or_replace",BENIGN:"no_action"}[state]
class Ledger:
 def __init__(self,path):self.path=path
 def _write(self,data):
  fd,tmp=tempfile.mkstemp(dir=os.path.dirname(self.path),prefix=".fleet-")
  with os.fdopen(fd,"w") as target:json.dump(data,target,sort_keys=True);target.flush();os.fsync(target.fileno())
  os.replace(tmp,self.path)
 def observe(self,task,owner,event,now=None):
  now=time.time() if now is None else now; state=classify(task,owner,now); ctx=context(task,owner); payload={"event":event,"state":state,"context":ctx}; stable={k:ctx[k] for k in ("owner","handoff","commit","tests","proofs")}; notification={"state":state,"boss_action":action(state),"context":stable}; digest=hashlib.sha256(json.dumps(notification,sort_keys=True).encode()).hexdigest();os.makedirs(os.path.dirname(self.path),exist_ok=True)
  with open(self.path+".lock","a+") as lock:
   fcntl.flock(lock,fcntl.LOCK_EX)
   try:
    with open(self.path,encoding="utf-8") as source:data=json.load(source)
   except (OSError,ValueError):data={}
   prior=data.get(task["id"],{});changed=prior.get("digest")!=digest
   if changed:
    delivered=state==BENIGN;entry={"digest":digest,"state":state,"updated":now,"delivery":{"nightwatch":delivered,"boss":delivered}};data[task["id"]]=entry;self._write(data)
   else:
    entry=prior;default_delivered=state==BENIGN;entry.setdefault("delivery",{"nightwatch":default_delivered,"boss":default_delivered})
  projected={"monitorState":state,"monitorUpdated":entry.get("updated",now),"monitorAction":action(state)}
  metadata_changed=any(task.get(key)!=value for key,value in projected.items());task.update(projected)
  pending=[target for target in ("nightwatch","boss") if not entry.get("delivery",{}).get(target,False)]
  if not changed and not metadata_changed and not pending:return None
  return {**payload,"task_id":task["id"],"boss_action":action(state),"digest":digest,"changed":changed or metadata_changed,"pending":pending}
 def ack(self,task_id,digest,target):
  if target not in {"nightwatch","boss"}:raise ValueError("invalid fleet delivery target")
  os.makedirs(os.path.dirname(self.path),exist_ok=True)
  with open(self.path+".lock","a+") as lock:
   fcntl.flock(lock,fcntl.LOCK_EX)
   try:
    with open(self.path,encoding="utf-8") as source:data=json.load(source)
   except (OSError,ValueError):data={}
   entry=data.get(task_id,{})
   if entry.get("digest")!=digest:return False
   delivery=entry.setdefault("delivery",{})
   if delivery.get(target):return True
   delivery[target]=True;self._write(data);return True
def message(o):
 c=o["context"];return f"[fleet-monitor] event={o['event']} card={o['task_id']} state={o['state']} owner={c['owner']} handoff={c['handoff']} commit={c['commit']} tests={c['tests']} boss_action={o['boss_action']}"
