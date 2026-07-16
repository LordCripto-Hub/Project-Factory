#!/usr/bin/env python3
from __future__ import annotations
import http.client, http.cookies, http.server, json, os, secrets, subprocess, threading, time
import urllib.parse
from mpcommon import *

HOST=ENV.get("BIND_ADDR","0.0.0.0"); PORT=int(ENV.get("HUD_PORT","9900")); TODO_PORT=int(ENV.get("TODO_PORT","9933"))
SECRET=ENV["QUEUE_SECRET"]; DEAD=float(ENV.get("QUEUE_DEAD_AFTER","20")); START=time.time()
CLIENTS={}; AGENTS={}; TASKS={}; BROWSER=set(); LOCK=threading.RLock()
QUEUE_PATH=os.path.realpath(os.environ.get("QUEUE_STATE_PATH") or os.path.join(ROOT,"run","control-queue.json"))
TASK_TYPES={"send","peek","kill","spawn","answer","revive"}
TASK_STATUSES={"queued","delivered","done","failed","uncertain"}
TERMINAL_TASK_STATUSES={"done","failed","uncertain"}
TERMINAL_TASK_LIMIT=500

def now():return time.time()

def _valid_task(task_id, row):
    return bool(
        isinstance(task_id,str) and task_id
        and isinstance(row,dict) and row.get("task_id")==task_id
        and row.get("type") in TASK_TYPES
        and row.get("status") in TASK_STATUSES
        and isinstance(row.get("target_agent"),str)
        and isinstance(row.get("payload"),dict)
    )

def persist_tasks(path=QUEUE_PATH,timestamp=None):
    current=now() if timestamp is None else float(timestamp)
    with LOCK:
        active=[];terminal=[]
        for task_id,row in TASKS.items():
            if not _valid_task(task_id,row):continue
            (terminal if row.get("status") in TERMINAL_TASK_STATUSES else active).append((task_id,row))
        terminal.sort(key=lambda item:float(item[1].get("completed_at") or item[1].get("recovered_at") or item[1].get("created_at") or 0),reverse=True)
        selected=active+terminal[:TERMINAL_TASK_LIMIT]
        TASKS.clear();TASKS.update((task_id,dict(row)) for task_id,row in selected)
        atomic_json(path,{"schemaVersion":1,"updatedAt":current,"tasks":TASKS},mode=0o600)

def load_tasks(path=QUEUE_PATH,timestamp=None):
    current=now() if timestamp is None else float(timestamp)
    body=load_json(path,{})
    rows=body.get("tasks",{}) if isinstance(body,dict) and body.get("schemaVersion")==1 else {}
    recovered={};changed=False
    for task_id,row in rows.items() if isinstance(rows,dict) else ():
        if not _valid_task(task_id,row):continue
        item=dict(row)
        if item.get("status")=="delivered":
            item.update(status="uncertain",recovery="server_restart_after_delivery",recovered_at=current)
            changed=True
        recovered[task_id]=item
    with LOCK:TASKS.clear();TASKS.update(recovered)
    if changed:persist_tasks(path,current)
    return {task_id:dict(row) for task_id,row in TASKS.items()}

def claim_tasks_for_host(host,path=QUEUE_PATH,timestamp=None):
    current=now() if timestamp is None else float(timestamp);out=[]
    with LOCK:
        for row in TASKS.values():
            if row.get("status")=="queued" and row.get("target_agent","").split("/",1)[0]==host:
                row.update(status="delivered",delivered_at=current,attempt=max(1,int(row.get("attempt") or 0)))
                out.append(dict(row))
        if out:persist_tasks(path,current)
    return out

def complete_task(task_id,ok,result,path=QUEUE_PATH,timestamp=None):
    current=now() if timestamp is None else float(timestamp)
    with LOCK:
        if task_id not in TASKS:raise ValueError("unknown task")
        TASKS[task_id].update(status="done" if ok else "failed",ok=bool(ok),result=result,completed_at=current)
        persist_tasks(path,current)
        return dict(TASKS[task_id])

def retry_task(task_id,path=QUEUE_PATH,timestamp=None):
    current=now() if timestamp is None else float(timestamp)
    with LOCK:
        row=TASKS.get(task_id)
        if not row:raise ValueError("unknown task")
        if row.get("status") not in {"failed","uncertain"}:raise ValueError("task is not retryable")
        for key in ("delivered_at","completed_at","recovered_at","recovery","ok","result"):
            row.pop(key,None)
        row.update(status="queued",retried_at=current,attempt=max(1,int(row.get("attempt") or 1))+1)
        persist_tasks(path,current)
        return dict(row)
def clean():
    while True:
        time.sleep(2)
        with LOCK:
            stale=[h for h,c in CLIENTS.items() if now()-c.get("last_seen",0)>DEAD]
            for h in stale:
                CLIENTS.pop(h,None)
                for aid in [a for a,r in AGENTS.items() if r.get("host")==h]:AGENTS.pop(aid,None)
threading.Thread(target=clean,daemon=True).start()

def canonical_agent(body):
    aid=body["agent_id"]; h,s,t=parse_agent_id(aid)
    return {**body,"agent_id":aid,"host":h,"session":s,"tab":t,"backend":body.get("backend","claude"),
            "state":body.get("state","alive"),"boss_id":body.get("boss_id","") or "","is_master":bool(body.get("is_master")),
            "summary":body.get("summary", ""),"tmux_target":f"mc-{s}:{t}","ts":now()}

def reconcile_host_agents(host, rows):
    incoming={}
    for row in rows:
        try:
            record=canonical_agent(row)
            if record.get("host") == host:
                incoming[record["agent_id"]]=record
        except Exception:
            continue
    with LOCK:
        for aid,record in list(AGENTS.items()):
            if record.get("host") == host and aid not in incoming:
                AGENTS.pop(aid,None)
        AGENTS.update(incoming)
    return list(incoming.values())

def joined_agents():
    rr={r.get("agent_id"):r for r in load_roster()}
    out=[]
    with LOCK: rows=list(AGENTS.values()); clients=dict(CLIENTS)
    for a in rows:
        r=rr.get(a["agent_id"],{}); z={**r,**a}; base=clients.get(a["host"],{}).get("attach_base","")
        if any(x in base for x in ("127.0.0.1","localhost","0.0.0.0","[::]")):base=""
        z["attach_base"]=base; z["attach_url"]=(f"{base}/?arg=-t&arg={urllib.parse.quote(z['tmux_target'],safe=':-')}" if base else "")
        z["spawn_cmd"]=r.get("spawn_cmd",z.get("spawn_cmd","")); z["revive_cmd"]="mp revive "+a["agent_id"]
        st=load_json(status_path(a["agent_id"]),{})
        if st:z["summary"]=st.get("summary") or z.get("summary","");z["status"]=st.get("status","idle")
        else:z["status"]="idle"
        out.append(z)
    return sorted(out,key=lambda x:(not x.get("is_master",False),x["agent_id"]))

class Handler(http.server.BaseHTTPRequestHandler):
    server_version="MyPeopleQueue/2"
    def log_message(self,fmt,*args):
        with open(os.path.join(ROOT,"run","queue-server.log"),"a",encoding="utf-8") as f:f.write(f"{time.time()} {self.address_string()} {fmt%args}\n")
    def browser_token(self):
        c=http.cookies.SimpleCookie();
        try:c.load(self.headers.get("Cookie", ""))
        except:pass
        return c.get("mp_session").value if c.get("mp_session") else ""
    def authed(self):return secrets.compare_digest(self.headers.get("X-Queue-Secret", ""),SECRET) or self.browser_token() in BROWSER
    def send_bytes(self,data,status=200,ctype="application/json",cookie=False,headers=None,head=False):
        self.send_response(status);self.send_header("Content-Type",ctype);self.send_header("Cache-Control","no-cache, no-store, must-revalidate");self.send_header("Pragma","no-cache");self.send_header("Expires","0")
        if cookie:
            tok=secrets.token_urlsafe(32);BROWSER.add(tok);self.send_header("Set-Cookie",f"mp_session={tok}; HttpOnly; Path=/; SameSite=Lax")
        for k,v in (headers or []):
            if k.lower() not in ("content-length","connection","transfer-encoding","set-cookie"):self.send_header(k,v)
        self.send_header("Content-Length",str(len(data)));self.end_headers()
        if not head:self.wfile.write(data)
    def json(self,obj,status=200,**kw):self.send_bytes(json.dumps(obj,ensure_ascii=False).encode(),status,"application/json; charset=utf-8",**kw)
    def page(self,name,head=False):
        try:data=open(os.path.join(ROOT,"bin",name),"rb").read()
        except FileNotFoundError:return self.json({"error":"asset_missing"},500)
        self.send_bytes(data,200,"text/html; charset=utf-8",cookie=True,head=head)
    def proxy(self,head=False):
        conn=http.client.HTTPConnection("127.0.0.1",TODO_PORT,timeout=20)
        headers={k:v for k,v in self.headers.items() if k.lower() not in ("host","content-length","connection")}
        headers["X-Queue-Secret"]=SECRET
        body=None
        if self.command in ("POST","PUT","PATCH"):
            body=self.rfile.read(int(self.headers.get("Content-Length","0") or 0))
            headers["Content-Length"]=str(len(body))
        try:
            conn.request(self.command,self.path,body=body,headers=headers);r=conn.getresponse();data=r.read()
            # Page proxy mints this origin's cookie so its first same-origin request succeeds.
            page=self.path.split("?",1)[0] in ("/","/todos","/wall","/terminal-graph","/terminal","/todo/terminal")
            self.send_bytes(data,r.status,r.getheader("Content-Type","application/octet-stream"),cookie=page,headers=r.getheaders(),head=head)
        except Exception as e:self.json({"error":"todo_proxy_unavailable","detail":str(e)},502)
        finally:conn.close()
    def do_HEAD(self):self.route(True)
    def do_GET(self):self.route(False)
    def route(self,head=False):
        path=urllib.parse.urlparse(self.path).path
        if path=="/favicon.ico":self.send_bytes(b"",204,"image/x-icon",head=head);return
        if path=="/health":return self.json({"status":"ok","uptime":int(now()-START),"build":int(os.path.getmtime(os.path.join(ROOT,"bin","dashboard.html"))) if os.path.exists(os.path.join(ROOT,"bin","dashboard.html")) else 0},head=head)
        if path in ("/dashboard","/dashboard/"):return self.page("dashboard.html",head)
        if path=="/" or path.startswith(("/todos","/wall","/terminal-graph","/terminal","/assets/","/voice/","/todo/","/nightwatch/")):return self.proxy(head)
        if not self.authed():return self.json({"ok":False,"error":"unauthorized"},401,head=head)
        if path=="/clients":
            with LOCK:return self.json(list(CLIENTS.values()),head=head)
        if path=="/agents":return self.json(joined_agents(),head=head)
        if path=="/roster":
            rows=[]
            for r in load_roster():rows.append({**r,"revive_cmd":"mp revive "+r.get("agent_id","")})
            return self.json(rows,head=head)
        if path=="/task/poll":
            host=urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query).get("hostname",[""])[0];out=[]
            out=claim_tasks_for_host(host)
            return self.json(out,head=head)
        if path.startswith("/task/"):
            tid=path.rsplit("/",1)[-1]
            with LOCK:return self.json(TASKS.get(tid,{"error":"unknown_task"}),200 if tid in TASKS else 404,head=head)
        self.json({"error":"not_found"},404,head=head)
    def read_json(self):
        n=int(self.headers.get("Content-Length","0") or 0)
        if n>8*1024*1024:raise ValueError("body too large")
        return json.loads(self.rfile.read(n) or b"{}")
    def do_POST(self):
        path=urllib.parse.urlparse(self.path).path
        if path.startswith(("/todo/","/voice/","/nightwatch/")) or path in ("/",):return self.proxy(False)
        if not self.authed():return self.json({"ok":False,"error":"unauthorized"},401)
        try:b=self.read_json()
        except Exception as e:return self.json({"ok":False,"error":"invalid_json","detail":str(e)},400)
        if path=="/heartbeat":
            h=b.get("hostname",""); base=b.get("attach_base","")
            if any(x in base for x in ("127.0.0.1","localhost","0.0.0.0")):base=""
            client={"hostname":h,"attach_base":base,"substrate_ready":bool(b.get("substrate_ready")),"last_seen":now(),
                    "purpose":b.get("purpose","mypeople"),"node_type":b.get("node_type","system-agent"),"recording_url":b.get("recording_url",""),"state":b.get("state","hydrating")}
            with LOCK:
                CLIENTS[h]=client
            reconcile_host_agents(h,b.get("agents",[]))
            return self.json({"ok":True})
        if path=="/agents/register":
            try:r=canonical_agent(b)
            except Exception as e:return self.json({"ok":False,"error":str(e)},400)
            with LOCK:AGENTS[r["agent_id"]]=r
            return self.json({"ok":True})
        if path=="/agents/unregister":
            with LOCK:AGENTS.pop(b.get("agent_id",""),None)
            return self.json({"ok":True})
        if path=="/task/submit":
            typ=b.get("type") or b.get("action")
            if typ not in ("send","peek","kill","spawn","answer","revive"):return self.json({"ok":False,"error":"invalid_type"},400)
            tid=secrets.token_hex(12);t={"task_id":tid,"type":typ,"target_agent":b.get("target_agent",""),"payload":b.get("payload",{}),"status":"queued","created_at":now()}
            with LOCK:TASKS[tid]=t;persist_tasks()
            return self.json({"task_id":tid})
        if path=="/task/result":
            tid=b.get("task_id","")
            try:complete_task(tid,bool(b.get("ok")),b.get("result"))
            except ValueError:return self.json({"ok":False,"error":"unknown_task"},404)
            return self.json({"ok":True})
        if path=="/task/retry":
            try:return self.json({"ok":True,"task":retry_task(str(b.get("task_id") or ""))})
            except ValueError as error:return self.json({"ok":False,"error":str(error)},400)
        if path=="/revive":
            aid=b.get("agent_id","")
            try:
                p=subprocess.run([os.path.join(ROOT,"bin","mp"),"revive",aid],capture_output=True,text=True,timeout=30)
                return self.json({"ok":p.returncode==0,"result":p.stdout or p.stderr},200 if p.returncode==0 else 400)
            except Exception as e:return self.json({"ok":False,"error":str(e)},500)
        self.json({"error":"not_found"},404)

if __name__=="__main__":
    os.makedirs(os.path.join(ROOT,"run"),exist_ok=True)
    load_tasks()
    http.server.ThreadingHTTPServer((HOST,PORT),Handler).serve_forever()
