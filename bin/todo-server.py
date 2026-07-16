#!/usr/bin/env python3
from __future__ import annotations
import cgi, copy, hashlib, http.client, http.cookies, http.server, io, json, mimetypes, os, pathlib, re, secrets, shutil, subprocess, threading, time
import urllib.parse, urllib.request
from mpcommon import *

BIND=ENV.get("BIND_ADDR","0.0.0.0");PORT=int(ENV.get("TODO_PORT","9933"));HUD=int(ENV.get("HUD_PORT","9900"))
SECRET=ENV["QUEUE_SECRET"]; NW_TOKEN=ENV.get("NIGHTWATCH_TOKEN",""); HOST_ID=ENV.get("HOST_ID",os.uname().nodename.split('.')[0])
BOSS=ENV.get("BOSS_AGENT","main:Boss");BOSS_FULL=full_agent_id(BOSS);NW_AGENT=ENV.get("NIGHTWATCH_AGENT",f"{HOST_ID}/nightwatch:Nightwatch")
BOARD_PATH=os.path.realpath(os.environ.get("BOARD_PATH",os.path.join(ROOT,"todos","board.v2.json")))
PROJECT_PROFILES_DIR=os.path.realpath(ENV.get("PROJECT_PROFILES_DIR",os.path.join(ROOT,"run","project-profiles")))
TODOS_DIR=os.path.dirname(BOARD_PATH);PROOFS_DIR=os.path.join(TODOS_DIR,"proofs");INBOX_LOG=os.path.join(TODOS_DIR,"boss-inbox.log")
os.makedirs(os.path.join(ROOT,"run"),exist_ok=True)
SESSIONS=set();TOKENS={};START=time.time();STORE_LOCK=threading.RLock()
VALID_STATES={"needs_brainstorm","working","review","done","blocked","cancelled","recurring"};TERMINAL={"done","cancelled"}
PROJECT_SLUG_RE=re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")

def validate_project_slug(value,*,allow_empty=False):
    value=str(value or "").strip()
    if allow_empty and not value:return ""
    if len(value)>64 or not PROJECT_SLUG_RE.fullmatch(value):raise ValueError("invalid_project_slug")
    return value

def validate_context_question(value):
    value=re.sub(r"[\x00-\x1f\x7f]+"," ",str(value or "")).strip()
    if len(value)>500:raise ValueError("context_question_too_long")
    return value

def available_project_slugs():
    directory=pathlib.Path(PROJECT_PROFILES_DIR)
    if not directory.is_dir():return []
    values=[]
    for path in directory.glob("*.json"):
        try:
            slug=validate_project_slug(path.stem)
            data=json.loads(path.read_text(encoding="utf-8"))
            if data.get("slug")==slug:values.append(slug)
        except (OSError,ValueError,json.JSONDecodeError):continue
    return sorted(set(values))

def default_board():return {"version":2,"order":[],"pinSeq":0,"tasks":{}}
def blank_board():return default_board()
def owner_event(action,agent_id="",previous="",by="system"):
    return {"id":secrets.token_hex(6),"action":action,"kind":action,"agent_id":agent_id,"previous":previous,"by":by,"ts":time.time()}
def normalize_task(t):
    defaults={"text":"","state":"needs_brainstorm","assignee":"","doneCondition":"","projectSlug":"","contextQuestion":"","evidencePolicy":"optional","workToDone":False,"comments":[],"proofs":[],"unread":0,"verified":False,"pingsToBoss":0,"pinned":False,"pinRank":None,"test":False,"ownerHistory":[],"ownerNeedsReplacement":False,"updated":time.time()}
    for k,v in defaults.items():
        if k not in t or t[k] is None:t[k]=copy.deepcopy(v)
    if t.get("evidencePolicy") not in ("required","optional"):t["evidencePolicy"]="optional"
    return t

def migrate(board):
    changed=False
    board.setdefault("version",2);board.setdefault("order",[]);board.setdefault("pinSeq",0);board.setdefault("tasks",{})
    for tid,t in board["tasks"].items():
        t.setdefault("id",tid)
        if t.get("ownerHistory") is None:
            t["ownerHistory"]=[];changed=True
            if t.get("assignee") and not any(x.get("kind")=="migrated_existing_owner" for x in t["ownerHistory"]):
                t["ownerHistory"].append(owner_event("migrated_existing_owner",t["assignee"],"","system"))
        if t.get("ownerNeedsReplacement") is None:t["ownerNeedsReplacement"]=False;changed=True
        before=json.dumps(t,sort_keys=True);normalize_task(t);changed |= before != json.dumps(t,sort_keys=True)
    board["order"]=[x for x in board["order"] if x in board["tasks"]]
    for x in board["tasks"]:
        if x not in board["order"]:board["order"].append(x);changed=True
    return changed

def migrate_legacy_owner_fields(board):return migrate(board)

def load_board(do_migrate=True):
    b=load_json(BOARD_PATH,blank_board())
    if not isinstance(b,dict):b=blank_board()
    if do_migrate and migrate(b):save_board(b,allow_shrink=True)
    return b

def task_count(b):return len((b or {}).get("tasks",{}))
def prune(pattern,keep=20):
    files=sorted(pathlib.Path(TODOS_DIR).glob(pattern),key=lambda p:p.stat().st_mtime,reverse=True)
    for p in files[keep:]:
        try:p.unlink()
        except OSError:pass

def save_board(board,allow_shrink=False):
    os.makedirs(TODOS_DIR,exist_ok=True);old=load_json(BOARD_PATH,blank_board())
    if not allow_shrink and task_count(old)>5 and task_count(board)<task_count(old)*.5:
        suspect=BOARD_PATH+f".SUSPECT.{int(time.time())}";atomic_json(suspect,board);return False
    if os.path.exists(BOARD_PATH):
        backup=BOARD_PATH+f".bak.{time.time_ns()}";shutil.copy2(BOARD_PATH,backup);prune(os.path.basename(BOARD_PATH)+".bak.*")
    atomic_json(BOARD_PATH,board);return True

def ordered_ids(b):
    pins=sorted((x for x in b["order"] if b["tasks"][x].get("pinned")),key=lambda x:(b["tasks"][x].get("pinRank") or 0))
    return pins+[x for x in b["order"] if x not in pins]

def safe_title(t):return re.sub(r"\s+"," ",t.get("text","")).strip()[:160]
def append_log(message):
    os.makedirs(TODOS_DIR,exist_ok=True)
    with open(INBOX_LOG,"a",encoding="utf-8") as f:f.write(message+"\n")

def mp_send(agent,msg,label="MP_SEND"):
    p=subprocess.run([os.environ.get("MYPEOPLE_MP_BIN",os.path.join(ROOT,"bin","mp")),"send",agent,msg],capture_output=True,text=True,timeout=15)
    append_log(f"{label} -> {agent} rc={p.returncode} :: {msg[:500]}");return p.returncode
def ping_boss(msg): return mp_send(BOSS_FULL,msg)

def fanout(task,msg,by=""):
    if task.get("test"):return
    if by != BOSS_FULL:task["pingsToBoss"]=int(task.get("pingsToBoss",0))+1;ping_boss(msg)
    if by != NW_AGENT:mp_send(NW_AGENT,"[nightwatch] "+msg)

def roster_map():
    try:
        rows=queue_get("/roster")
    except Exception:
        rows=load_roster()
    return {r.get("agent_id"):r for r in rows if isinstance(r,dict)}
def valid_owner(task,aid):
    r=roster_map().get(aid)
    return bool(r and r.get("state")=="alive" and not r.get("retired") and r.get("boss_id")==BOSS_FULL and r.get("lifecycle")=="owner" and r.get("owner_task_id")==task["id"])

def classify_media(kind,url,filename="",ctype=""):
    probe=(filename or urllib.parse.urlparse(url or "").path).lower();ct=(ctype or "").lower()
    if ct.startswith("image/") or re.search(r"\.(png|jpe?g|gif|webp|svg)$",probe):return "image"
    if ct.startswith("video/") or re.search(r"\.(mp4|webm|mov|m4v)$",probe):return "video"
    if url and (url.startswith("http://") or url.startswith("https://")) and not filename:return "link" if kind in ("","text",None) else kind
    if filename or (url and url.startswith("/todo/proof")):return kind if kind in ("image","video") else "file"
    return kind if kind in ("image","video","link","file") else "text"

def proof_metadata(content,filename,ctype,by=""):
    content=content or b""
    return {"filename":os.path.basename(filename or "artifact"),"mime":ctype or "application/octet-stream","bytes":len(content),"sha256":hashlib.sha256(content).hexdigest(),"by":str(by or "")}

def transition_verified(old_state,new_state,requested,current):
    if new_state=="done" and old_state!="done":return bool(requested)
    if old_state in TERMINAL and new_state not in TERMINAL:return False
    return bool(current if requested is None else requested)

def done_transition_error(task,state,verified):
    if state!="done":return None
    if task.get("evidencePolicy")=="required" and not task.get("proofs"):return "evidence_required"
    if not verified:return "verification_required"
    return None

def proof_file_path(task_id,filename):
    tid=str(task_id or "");name=str(filename or "")
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,128}",tid):return None
    if not name or name in (".","..") or os.path.basename(name)!=name:return None
    root=os.path.realpath(PROOFS_DIR);directory=os.path.realpath(os.path.join(root,tid));path=os.path.realpath(os.path.join(directory,name))
    if not directory.startswith(root+os.sep) or not path.startswith(directory+os.sep):return None
    return path

def safe_terminal_text(text):
    return re.sub(r"[\x00-\x1f\x7f]+"," ",str(text or "")).strip()[:8000]

def queue_get(path):return http_json(path,base=ENV.get("QUEUE_URL","http://127.0.0.1:9900"))

def geometry():
    out={}
    try:
        p=run_tmux(["list-windows","-a","-F","#{session_name}\t#{window_name}\t#{window_width}\t#{window_height}"],capture=True)
        for line in p.stdout.splitlines():
            s,w,c,r=line.split("\t");out[f"{s}:{w}"]=(int(c),int(r))
    except Exception:pass
    return out

def wall_data(graph=False):
    agents=queue_get("/agents");rr=roster_map();geo=geometry();rows=[]
    for a in agents:
        r=rr.get(a["agent_id"],{})
        if a.get("state")!="alive" or r.get("retired"):continue
        if a.get("host")==HOST_ID and a.get("tmux_target") not in geo:continue
        status=a.get("status","idle");display=status if status in ("starting","working","idle","blocked") else "idle"
        cols,lines=geo.get(a["tmux_target"],(120,36))
        rows.append({"agent_id":a["agent_id"],"boss_id":a.get("boss_id",""),"is_master":bool(a.get("is_master")),"target":a["tmux_target"],"tmux_target":a["tmux_target"],"state":display,"host":a.get("host"),"cols":cols,"rows":lines,"read_port":int(ENV.get("TTYD_RO_PORT","7682")),"write_port":int(ENV.get("TTYD_PORT","7681"))})
    rows.sort(key=lambda x:(x["state"]!="working",not x["is_master"],x["agent_id"]))
    if not graph:return rows
    live={x["agent_id"] for x in rows};edges=[{"parent":x["boss_id"],"child":x["agent_id"]} for x in rows if x["boss_id"] in live]
    b=load_board();tasks=[]
    for tid in ordered_ids(b):
        t=b["tasks"][tid];owner=t.get("assignee","");tasks.append({"id":tid,"title":t.get("text",""),"state":t.get("state"),"assignee":owner,"owner_live":owner in live,"archived":t.get("state") in TERMINAL,"pinned":bool(t.get("pinned")),"updated":t.get("updated",0),"href":"/terminal-graph?task="+urllib.parse.quote(tid)})
    return {"agents":rows,"edges":edges,"tasks":tasks,"states":sorted(VALID_STATES)}

def idle_watch():
    fired=set();minutes=float(ENV.get("NIGHTWATCH_IDLE_MIN","30"))
    while True:
        time.sleep(min(30,max(2,minutes*15)))
        try:
            b=load_board()
            for tid,t in b["tasks"].items():
                if t.get("test") or t.get("state") in TERMINAL:continue
                if time.time()-float(t.get("updated",0))>=minutes*60 and tid not in fired:
                    mp_send(NW_AGENT,f"[nightwatch] idle task {tid} \"{safe_title(t)}\"");fired.add(tid)
        except Exception:pass
threading.Thread(target=idle_watch,daemon=True).start()

class Handler(http.server.BaseHTTPRequestHandler):
    server_version="MyPeopleTodo/2"
    def log_message(self,fmt,*args):
        with open(os.path.join(ROOT,"run","todo-server.log"),"a",encoding="utf-8") as f:f.write(f"{time.time()} {fmt%args}\n")
    def cookies(self):
        c=http.cookies.SimpleCookie()
        try:c.load(self.headers.get("Cookie",""))
        except:pass
        return c
    def auth_kind(self):
        q=self.headers.get("X-Queue-Secret","");n=self.headers.get("X-Nightwatch-Token","")
        if NW_TOKEN and (secrets.compare_digest(q,NW_TOKEN) or secrets.compare_digest(n,NW_TOKEN)):return "nightwatch"
        if secrets.compare_digest(q,SECRET):return "machine"
        tok=self.cookies().get("mp_session");return "browser" if tok and tok.value in SESSIONS else ""
    def send_bytes(self,data,status=200,ctype="application/json",cookie=False,headers=None,head=False):
        self.send_response(status);self.send_header("Content-Type",ctype);self.send_header("Cache-Control","no-cache, no-store, must-revalidate");self.send_header("Pragma","no-cache");self.send_header("Expires","0")
        if cookie:
            t=secrets.token_urlsafe(32);SESSIONS.add(t);self.send_header("Set-Cookie",f"mp_session={t}; HttpOnly; Path=/; SameSite=Lax")
        for k,v in (headers or []):
            if k.lower() not in ("content-length","connection","transfer-encoding","set-cookie"):self.send_header(k,v)
        self.send_header("Content-Length",str(len(data)));self.end_headers()
        if not head:self.wfile.write(data)
    def json(self,o,status=200,**kw):self.send_bytes(json.dumps(o,ensure_ascii=False).encode(),status,"application/json; charset=utf-8",**kw)
    def page(self,name,head=False):
        try:data=open(os.path.join(ROOT,"bin",name),"rb").read()
        except FileNotFoundError:return self.json({"error":"asset_missing"},500)
        self.send_bytes(data,200,"text/html; charset=utf-8",cookie=True,head=head)
    def asset(self,name,ctype,head=False):
        try:data=open(os.path.join(ROOT,"bin",name),"rb").read()
        except FileNotFoundError:return self.json({"error":"asset_missing"},404)
        self.send_bytes(data,200,ctype,head=head)
    def proxy_hud(self,head=False):
        conn=http.client.HTTPConnection("127.0.0.1",HUD,timeout=20);headers={k:v for k,v in self.headers.items() if k.lower() not in ("host","content-length","connection")};headers["X-Queue-Secret"]=SECRET;body=None
        if self.command=="POST":body=self.rfile.read(int(self.headers.get("Content-Length","0") or 0));headers["Content-Length"]=str(len(body))
        try:
            conn.request(self.command,self.path,body,headers);r=conn.getresponse();data=r.read();self.send_bytes(data,r.status,r.getheader("Content-Type","application/octet-stream"),cookie=urllib.parse.urlparse(self.path).path=="/dashboard",headers=r.getheaders(),head=head)
        except Exception as e:self.json({"error":"hud_proxy_unavailable","detail":str(e)},502)
        finally:conn.close()
    def do_HEAD(self):self.route_get(True)
    def do_GET(self):self.route_get(False)
    def route_get(self,head=False):
        u=urllib.parse.urlparse(self.path);p=u.path
        if p=="/favicon.ico":return self.send_bytes(b"",204,"image/x-icon",head=head)
        if p=="/health":return self.json({"status":"ok","uptime":int(time.time()-START),"build":max((int(os.path.getmtime(os.path.join(ROOT,"bin",x))) for x in ("todos.html","mypeople-ui.css","voice-dock.js") if os.path.exists(os.path.join(ROOT,"bin",x))),default=0)},head=head)
        if p=="/assets/mypeople-ui.css":return self.asset("mypeople-ui.css","text/css; charset=utf-8",head)
        if p=="/assets/voice-dock.js":return self.asset("voice-dock.js","application/javascript; charset=utf-8",head)
        if p in ("/","/todos"):return self.page("todos.html",head)
        if p=="/wall":return self.page("wall.html",head)
        if p=="/terminal-graph":return self.page("terminal-graph.html",head)
        if p=="/dashboard" or p.startswith("/dashboard/") or p in ("/agents","/roster","/clients"):return self.proxy_hud(head)
        if not self.auth_kind():return self.json({"ok":False,"error":"unauthorized"},401,head=head)
        if p.startswith("/todo/proof-file/"):
            name=os.path.basename(urllib.parse.unquote(p.rsplit('/',1)[-1]));path=os.path.realpath(os.path.join(PROOFS_DIR,name));base=os.path.realpath(PROOFS_DIR)+os.sep
            if not path.startswith(base) or not os.path.isfile(path):return self.json({"error":"not_found"},404)
            return self.send_bytes(open(path,"rb").read(),200,mimetypes.guess_type(path)[0] or "application/octet-stream",head=head)
        m=re.fullmatch(r"/todo/proof/([^/]+)/([^/]+)",p)
        if m:
            tid,name=map(urllib.parse.unquote,m.groups());path=proof_file_path(tid,name)
            if not path or not os.path.isfile(path):return self.json({"error":"not_found"},404)
            return self.send_bytes(open(path,"rb").read(),200,mimetypes.guess_type(path)[0] or "application/octet-stream",head=head)
        if p=="/todo/board":
            b=load_board();o=copy.deepcopy(b);o["displayOrder"]=ordered_ids(b);o["boardPath"]=BOARD_PATH;o["projectSlugs"]=available_project_slugs();return self.json(o,head=head)
        if p in ("/todo/attach","/todo/terminal","/terminal"):
            aid=urllib.parse.parse_qs(u.query).get("agent",[""])[0]
            try:
                h,s,t=parse_agent_id(aid);clients=queue_get("/clients");local=h==HOST_ID
                base="" if h==HOST_ID else next((x.get("attach_base","") for x in clients if x.get("hostname")==h),"")
                target=f"mc-{s}:{t}";ok=window_exists(target) if local else bool(base)
                if not ok:return self.json({"ok":False,"error":"agent_unavailable"},404)
                if local:
                    request_host=self.headers.get("Host","localhost").rsplit(":",1)[0]
                    base=f"http://{request_host}:7681"
                parts=urllib.parse.urlsplit(base);direct=urllib.parse.urlunsplit((parts.scheme or "http",parts.netloc,"/",urllib.parse.urlencode([("arg","-t"),("arg",target)]),""))
                if p=="/todo/attach":return self.json({"ok":True,"target":target,"base":base,"direct":direct,"agent":aid})
                return self.page("terminal.html",head)
            except Exception:return self.json({"ok":False,"error":"invalid_agent"},400)
        if p=="/todo/wall":return self.json(wall_data(),head=head)
        if p=="/todo/terminal-graph":return self.json(wall_data(True),head=head)
        self.json({"error":"not_found"},404,head=head)
    def read_body(self):
        n=int(self.headers.get("Content-Length","0") or 0)
        if n>32*1024*1024:raise ValueError("body too large")
        raw=self.rfile.read(n)
        if self.headers.get("Content-Type","").startswith("application/json"):return json.loads(raw or b"{}"),None
        return {},raw
    def nw_guard(self,kind,body):
        if kind!="nightwatch":return None
        claimed=body.get("by",body.get("actor",NW_AGENT))
        if claimed != NW_AGENT:return (403,{"ok":False,"error":"nightwatch_cannot_spoof"})
        return None
    def do_POST(self):
        p=urllib.parse.urlparse(self.path).path
        if p in ("/agents","/roster","/clients","/revive") or p.startswith("/dashboard"):return self.proxy_hud(False)
        kind=self.auth_kind()
        if not kind:return self.json({"ok":False,"error":"unauthorized"},401)
        try:body,raw=self.read_body()
        except Exception as e:return self.json({"ok":False,"error":"invalid_body","detail":str(e)},400)
        guard=self.nw_guard(kind,body)
        if guard:return self.json(guard[1],guard[0])
        if p=="/todo/update":return self.update(kind,body)
        if p=="/todo/comment":return self.comment(kind,body)
        if p=="/todo/status":return self.status(kind,body)
        if p=="/todo/proof":return self.proof(kind,body,raw)
        if p=="/voice/paste":return self.voice_paste(kind,body)
        if p=="/todo/owner":return self.owner(kind,body)
        if p=="/nightwatch/inbound":return self.inbound(kind,body)
        if p=="/nightwatch/outbound":return self.outbound(kind,body)
        self.json({"error":"not_found"},404)
    def update(self,kind,d):
        op=d.get("op")
        if any(k in d for k in ("parent","dependsOn","hardGate")) or op=="reorder":return self.json({"ok":False,"error":"unsupported_removed_feature"},400)
        if kind=="nightwatch" and op=="add":
            token=d.get("token","");item=TOKENS.get(token)
            if not item or item["used"] or item["expires"]<time.time() or item["text"]!=d.get("text",""):return self.json({"ok":False,"error":"nightwatch_cannot_create"},403)
            item["used"]=True
        if kind=="nightwatch" and op=="set" and (d.get("state")=="done" or d.get("done") is True or d.get("workToDone") is True):return self.json({"ok":False,"error":"nightwatch_cannot_done"},403)
        try:
            project_slug=(validate_project_slug(d.get("projectSlug"),allow_empty=True) if "projectSlug" in d else None) if op=="set" else validate_project_slug(d.get("projectSlug",""),allow_empty=True) if op=="add" else None
            context_question=(validate_context_question(d.get("contextQuestion")) if "contextQuestion" in d else None) if op=="set" else validate_context_question(d.get("contextQuestion","")) if op=="add" else None
        except ValueError as e:
            return self.json({"ok":False,"error":str(e)},400)
        with STORE_LOCK:
            b=load_board();tid=d.get("id","")
            if op=="add":
                if "assignee" in d:return self.json({"ok":False,"error":"assignee_controlled"},400)
                title=str(d.get("text","")).strip();is_test=bool(d.get("test"));policy=d.get("evidencePolicy","optional" if is_test else "required")
                if not title:return self.json({"ok":False,"error":"text_required"},400)
                if policy not in ("required","optional"):return self.json({"ok":False,"error":"invalid_evidence_policy"},400)
                tid=secrets.token_hex(8);t=normalize_task({"id":tid,"text":title,"state":"needs_brainstorm","projectSlug":project_slug,"contextQuestion":context_question,"evidencePolicy":policy,"test":is_test,"created":time.time(),"updated":time.time()});b["tasks"][tid]=t;b["order"].insert(0,tid)
                if not t["test"]:fanout(t,f"[todo] task {tid} \"{safe_title(t)}\": added",d.get("by",d.get("actor","CEO")))
            elif tid not in b["tasks"]:return self.json({"ok":False,"error":"unknown_task"},404)
            elif op=="del":b["tasks"].pop(tid);b["order"]=[x for x in b["order"] if x!=tid]
            elif op in ("pin","unpin"):
                t=b["tasks"][tid]
                if op=="pin" and not t.get("pinned"):b["pinSeq"]=int(b.get("pinSeq",0))+1;t.update(pinned=True,pinRank=b["pinSeq"])
                elif op=="unpin":t.update(pinned=False,pinRank=None)
                t["updated"]=time.time()
            elif op=="set":
                if "assignee" in d:return self.json({"ok":False,"error":"assignee_controlled"},400)
                t=b["tasks"][tid];old=t.get("state");desired=d.get("state",old)
                if d.get("done") is True or d.get("workToDone") is True:desired="done"
                if desired not in VALID_STATES:return self.json({"ok":False,"error":"invalid_state"},400)
                policy=d.get("evidencePolicy",t.get("evidencePolicy","optional"))
                if policy not in ("required","optional"):return self.json({"ok":False,"error":"invalid_evidence_policy"},400)
                verified=transition_verified(old,desired,d.get("verified"),t.get("verified",False))
                probe={**t,"evidencePolicy":policy};err=done_transition_error(probe,desired,verified)
                if err:return self.json({"ok":False,"error":err},409)
                t["state"]=desired;t["evidencePolicy"]=policy
                for k in ("text","doneCondition","workToDone"):
                    if k in d:t[k]=d[k]
                if project_slug is not None:t["projectSlug"]=project_slug
                if context_question is not None:t["contextQuestion"]=context_question
                t["verified"]=verified
                t["updated"]=time.time();self.close_reopen(t,old,desired,d.get("by",d.get("actor","")))
                if old!=desired and not t.get("test"):fanout(t,f"[todo] task {tid} \"{safe_title(t)}\": {old} -> {desired}",d.get("by",d.get("actor","")))
            else:return self.json({"ok":False,"error":"invalid_op"},400)
            if not save_board(b):return self.json({"ok":False,"error":"catastrophic_shrink_quarantined"},409)
            return self.json({"ok":True,"id":tid})
    def close_reopen(self,t,old,new,by):
        if by!="CEO":return
        if old not in TERMINAL and new in TERMINAL and t.get("assignee"):
            t["ownerHistory"].append(owner_event("closed",t["assignee"],"","CEO"))
            if not t.get("test"):ping_boss(f"[todo] CLOSED by the CEO {t['id']}: kill owner {t['assignee']} and preserve history")
        elif old in TERMINAL and new not in TERMINAL:
            t["ownerNeedsReplacement"]=True;t["ownerHistory"].append(owner_event("reopen_requested","",t.get("assignee",""),"CEO"))
            if not t.get("test"):ping_boss(f"[todo] reopen {t['id']}: CREATE fresh --owner-task {t['id']}; do not reuse {t.get('assignee','')}")
    def comment(self,kind,d):
        tid=d.get("task_id","");by=d.get("by","");text=str(d.get("body", ""))
        if not text.strip():return self.json({"ok":False,"error":"body_required"},400)
        with STORE_LOCK:
            b=load_board();t=b["tasks"].get(tid)
            if not t:return self.json({"ok":False,"error":"unknown_task"},404)
            c={"id":secrets.token_hex(8),"by":by,"kind":"comment","body":text,"ts":time.time()};t["comments"].append(c)
            if by!="CEO":t["unread"]=int(t.get("unread",0))+1
            t["updated"]=time.time()
            if not t.get("test"):
                fanout(t,f"[todo] comment on {tid} owner={t.get('assignee','')} by {by}: {text[:800]}",by)
                if by=="CEO" and t.get("assignee") and not t.get("ownerNeedsReplacement"):
                    # The Boss remains authoritative; this explicit owner detail makes same-owner routing deterministic.
                    append_log(f"OWNER_ROUTE {tid} -> {t['assignee']}")
            save_board(b);return self.json({"ok":True,"comment":c})
    def status(self,kind,d):
        if kind=="nightwatch" and d.get("state")=="done":return self.json({"ok":False,"error":"nightwatch_cannot_done"},403)
        tid=d.get("task_id",d.get("id",""));state=d.get("state")
        if state not in VALID_STATES:return self.json({"ok":False,"error":"invalid_state"},400)
        with STORE_LOCK:
            b=load_board();t=b["tasks"].get(tid)
            if not t:return self.json({"ok":False,"error":"unknown_task"},404)
            old=t["state"];verified=transition_verified(old,state,d.get("verified"),t.get("verified",False));err=done_transition_error(t,state,verified)
            if err:return self.json({"ok":False,"error":err},409)
            t["state"]=state;t["verified"]=verified;t["updated"]=time.time();self.close_reopen(t,old,state,d.get("by",d.get("actor","")));save_board(b)
            if old!=state and not t.get("test"):fanout(t,f"[todo] task {tid} \"{safe_title(t)}\": {old} -> {state}",d.get("by",d.get("actor","")))
            return self.json({"ok":True})
    def proof(self,kind,d,raw):
        filename="";ctype="";content=None
        if raw is not None and self.headers.get("Content-Type","").startswith("multipart/form-data"):
            env={"REQUEST_METHOD":"POST","CONTENT_TYPE":self.headers.get("Content-Type"),"CONTENT_LENGTH":str(len(raw))};form=cgi.FieldStorage(fp=io.BytesIO(raw),environ=env,keep_blank_values=True)
            d={k:form.getvalue(k) for k in form.keys() if k!="file"};item=form["file"] if "file" in form else None
            if item is not None and getattr(item,"file",None):filename=os.path.basename(item.filename or "upload");ctype=item.type or "";content=item.file.read()
        tid=str(d.get("task_id","") or "");url=str(d.get("url","") or "");body=str(d.get("body","") or "");by=str(d.get("by","") or "")
        if content is None and not body.strip() and not url.strip():return self.json({"ok":False,"error":"evidence_required"},400)
        with STORE_LOCK:
            b=load_board();t=b["tasks"].get(tid)
            if not t:return self.json({"ok":False,"error":"unknown_task"},404)
            if content is not None:
                ext=os.path.splitext(filename)[1].lower() or mimetypes.guess_extension(ctype) or ".bin";name=secrets.token_hex(10)+ext;directory=os.path.join(PROOFS_DIR,tid);os.makedirs(directory,exist_ok=True)
                with open(os.path.join(directory,name),"wb") as handle:handle.write(content)
                url=f"/todo/proof/{urllib.parse.quote(tid)}/{urllib.parse.quote(name)}"
            k=classify_media(d.get("kind"),url,filename,ctype);audit=content if content is not None else (body or url).encode()
            label=filename or (os.path.basename(urllib.parse.urlparse(url).path) if url else ("evidence.txt" if k=="text" else "reference.url"))
            meta=proof_metadata(audit,label,ctype or ("text/plain" if k=="text" else "text/uri-list" if k=="link" else "application/octet-stream"),by)
            pr={"id":secrets.token_hex(8),"kind":k,"url":url if k!="text" else "","body":body,"ts":time.time(),**meta};t["proofs"].append(pr);t["updated"]=time.time();save_board(b);return self.json({"ok":True,"proof":pr})
    def voice_paste(self,kind,d):
        aid=str(d.get("agent","") or "");text=safe_terminal_text(d.get("text",""))
        if not text:return self.json({"ok":False,"error":"text_required"},400)
        try:h,s,t=parse_agent_id(aid);target=f"mc-{s}:{t}"
        except Exception:return self.json({"ok":False,"error":"invalid_agent"},400)
        record=roster_map().get(aid,{})
        if h!=HOST_ID or record.get("state")!="alive" or record.get("retired") or not window_exists(target):return self.json({"ok":False,"error":"agent_unavailable"},404)
        try:run_tmux(["set-buffer","--",text]);run_tmux(["paste-buffer","-d","-t",target])
        except Exception as e:return self.json({"ok":False,"error":"terminal_paste_failed","detail":str(e)},502)
        return self.json({"ok":True,"chars":len(text)})
    def owner(self,kind,d):
        if kind!="machine" or d.get("by")!=BOSS_FULL:return self.json({"ok":False,"error":"boss_only"},403)
        action=d.get("action");tid=d.get("task_id","");aid=d.get("agent_id","")
        if action not in ("assign","replace","reopen"):return self.json({"ok":False,"error":"invalid_action"},400)
        with STORE_LOCK:
            b=load_board();t=b["tasks"].get(tid)
            if not t:return self.json({"ok":False,"error":"unknown_task"},404)
            if not valid_owner(t,aid):return self.json({"ok":False,"error":"invalid_owner"},400)
            for x in b["tasks"].values():
                if x["id"]!=tid and x.get("assignee")==aid and x.get("state") not in TERMINAL:return self.json({"ok":False,"error":"owner_in_use"},409)
            prev=t.get("assignee","")
            if action=="assign" and prev and prev!=aid:return self.json({"ok":False,"error":"owner_exists"},409)
            if action=="reopen":
                if not t.get("ownerNeedsReplacement") or aid==prev:return self.json({"ok":False,"error":"fresh_owner_required"},409)
            if action=="replace" and prev and prev!=aid and not t.get("test"):ping_boss(f"[todo] replace {tid}: kill prior owner {prev}")
            t["assignee"]=aid;t["ownerNeedsReplacement"]=False
            # CEO approval is represented by review.  Assigning the fresh
            # Boss/worker owner is the next lifecycle edge and must be
            # visible immediately in both API responses and the polling UI.
            if t.get("state") in ("needs_brainstorm","review"):
                t["state"]="working";t["verified"]=False
            t["ownerHistory"].append(owner_event(action,aid,prev if prev!=aid else "",BOSS_FULL));t["updated"]=time.time()
            if not save_board(b):return self.json({"ok":False,"error":"catastrophic_shrink_quarantined"},409)
            return self.json({"ok":True,"assignee":aid,"previous":prev,"state":t["state"]})
    def inbound(self,kind,d):
        if kind!="machine":return self.json({"ok":False,"error":"unauthorized"},401)
        sender=str(d.get("from",""));text=str(d.get("text",""));event=f"[nightwatch] inbound {sender}: {text}";m=re.fullmatch(r"\s*Nightwatch,\s*create\s+(.+?)\s*",text,re.I)
        if m and ENV.get("CEO_WHATSAPP") and sender==ENV.get("CEO_WHATSAPP"):
            tok=secrets.token_urlsafe(24);bound=m.group(1);TOKENS[tok]={"text":bound,"expires":time.time()+float(ENV.get("NIGHTWATCH_TOKEN_TTL","600")),"used":False};event=f"[nightwatch] inbound CEO: create {json.dumps(bound)} token={tok}"
        mp_send(NW_AGENT,event);return self.json({"ok":True})
    def outbound(self,kind,d):
        if kind!="nightwatch":return self.json({"ok":False,"error":"nightwatch_only"},403)
        url=ENV.get("HERMES_SEND_URL","");ceo=ENV.get("CEO_WHATSAPP","")
        if not url or not ceo:return self.json({"ok":False,"error":"hermes_not_configured"},501)
        host=urllib.parse.urlparse(url).hostname or ""
        if host in ("127.0.0.1","localhost","0.0.0.0") or host.startswith("192.168."):return self.json({"ok":False,"error":"hermes_must_use_tailnet"},400)
        payload=json.dumps({"chatId":re.sub(r"\D","",ceo)+"@s.whatsapp.net","message":str(d.get("text",""))}).encode();req=urllib.request.Request(url,data=payload,method="POST",headers={"Content-Type":"application/json"})
        try:
            with urllib.request.urlopen(req,timeout=15) as r:return self.json({"ok":200<=r.status<300},200 if 200<=r.status<300 else 502)
        except Exception as e:return self.json({"ok":False,"error":"hermes_send_failed"},502)

if __name__=="__main__":
    os.makedirs(TODOS_DIR,exist_ok=True);load_board(True)
    http.server.ThreadingHTTPServer((BIND,PORT),Handler).serve_forever()
