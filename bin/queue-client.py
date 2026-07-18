#!/usr/bin/env python3
from __future__ import annotations
import json, os, subprocess, time, traceback
from mpcommon import *

HOST=ENV.get("HOST_ID",os.uname().nodename.split('.')[0]); INTERVAL=float(ENV.get("HEARTBEAT_INTERVAL","3"))
TAILSCALE_ENABLED = ENV.get("MYPEOPLE_TAILSCALE_ENABLED", "0") == "1"

def reconcile_prompt_idle(aid, target, status):
    """A provider's visible composer prompt is the event that work is complete."""
    if status.get("status") != "working" or time.time()-float(status.get("activity_updated_at",0)) < 2:
        return
    pane=run_tmux(["capture-pane","-p","-S","-30","-t",target],capture=True,check=False)
    if pane.returncode == 0 and any(marker in (pane.stdout or "") for marker in ("How can I help", "Try", "OpenAI Codex", "Claude Code")):
        write_status(aid,"idle",activity_event="composer_prompt_ready")

def tail_ip():
    if not TAILSCALE_ENABLED:
        return ""
    for cmd in (["tailscale","ip","-4"],["sudo","tailscale","--socket",os.path.join(ROOT,"run","tailscale-state","tailscaled.sock"),"ip","-4"]):
        try:
            p=subprocess.run(cmd,capture_output=True,text=True,timeout=5)
            for line in p.stdout.splitlines():
                if line.startswith("100."):return line.strip()
        except Exception:pass
    return ""

def live_roster():
    live=[]
    for row in load_roster():
        try:
            aid=row["agent_id"];h,s,t=parse_agent_id(aid)
            # Explicitly derive session/tab from agent_id if old roster omitted them.
            row={**row,"host":h,"session":row.get("session") or s,"tab":row.get("tab") or t}
            if window_exists(f"mc-{s}:{t}") and not row.get("retired"):
                row["state"]="alive";live.append(row)
                # Spawn records start at ``starting`` but no provider callback
                # is guaranteed to rewrite that file.  A successful heartbeat
                # is the authoritative proof that the window is live, so
                # close the one-way startup phase instead of exposing stale
                # status forever in the HUD.
                status=load_json(status_path(aid),{})
                if status.get("status")=="starting":
                    write_status(aid,"idle",status.get("summary",""),activity_event="bootstrap_ready",
                                 boss_id=status.get("boss_id",row.get("boss_id","")),
                                 backend=status.get("backend",row.get("backend","")))
                    row["status"]="idle"
                elif status.get("status"):
                    row["status"]=status["status"]
                reconcile_prompt_idle(aid,f"mc-{s}:{t}",status)
                status=load_json(status_path(aid),{})
                row["status"]=status.get("status","idle")
                if status.get("summary"):
                    row["summary"]=status["summary"]
        except Exception:continue
    atomic_json(agents_path(),live);return live

def heartbeat():
    ip = tail_ip()
    base = (
        f"http://{ip}:{ENV.get('TTYD_PORT', '7681')}"
        if ip
        else ENV.get("TTYD_PUBLIC_URL", "")
    )
    if any(x in base for x in ("127.0.0.1","localhost","0.0.0.0")):base=""
    http_json("/heartbeat","POST",{"hostname":HOST,"attach_base":base,"substrate_ready":True,
      "purpose":ENV.get("NODE_PURPOSE","mypeople"),"node_type":ENV.get("NODE_TYPE","system-agent"),
      "recording_url":ENV.get("NODE_RECORDING_URL",""),"state":load_json(os.path.join(ROOT,"run","hydration.json"),{}).get("state","ready"),"agents":live_roster()})

def execute(task):
    typ=task.get("type") or task.get("action");aid=task.get("target_agent","");p=task.get("payload") or {}
    if typ=="send":
        write_status(aid,"working",activity_event="queue_send")
        return tmux_send_message(tmux_target(aid),p.get("message")),"delivered"
    if typ=="peek":
        x=run_tmux(["capture-pane","-p","-S","-200","-t",tmux_target(aid)],capture=True);return True,x.stdout
    if typ=="kill":
        x=subprocess.run([os.path.join(ROOT,"bin","mp"),"kill",aid,"--reason",p.get("reason","")],capture_output=True,text=True);return x.returncode==0,x.stdout+x.stderr
    if typ=="revive":
        x=subprocess.run([os.path.join(ROOT,"bin","mp"),"revive",aid],capture_output=True,text=True);return x.returncode==0,x.stdout+x.stderr
    if typ=="answer":
        x=subprocess.run([os.path.join(ROOT,"bin","mp"),"answer",aid,str(p.get("choice",1))],capture_output=True,text=True);return x.returncode==0,x.stdout+x.stderr
    if typ=="spawn":
        boss=p.get("boss")
        if boss is not None and not str(boss).strip():return False,"empty boss"
        argv=[os.path.join(ROOT,"bin","mp"),"spawn",aid,"--backend",p.get("backend","claude")]
        if p.get("cwd"):argv += ["--cwd",p["cwd"]]
        if boss is not None:argv += ["--boss",boss]
        if p.get("is_master"):argv += ["--master"]
        model=p.get("model")
        if (
            model is None
            and not p.get("is_master")
            and not (
                p.get("backend") == "codex"
                and p.get("owner_task_id")
            )
        ):
            model=DEFAULT_ENG_MODEL
        if model:argv += ["--model",model]
        if p.get("owner_task_id"):argv += ["--owner-task",p["owner_task_id"]]
        elif p.get("temporary"):argv += ["--temporary"]
        x=subprocess.run(argv,capture_output=True,text=True,timeout=60);return x.returncode==0,x.stdout+x.stderr
    return False,"unknown type"

if __name__=="__main__":
    log=os.path.join(ROOT,"run","queue-client.log")
    while True:
        try:
            heartbeat()
            tasks=http_json("/task/poll?hostname="+urllib.parse.quote(HOST))
            if not isinstance(tasks,list):raise RuntimeError("poll must return array")
            for task in tasks:
                try:ok,result=execute(task)
                except Exception as e:ok,result=False,f"{e}\n{traceback.format_exc()}"
                http_json("/task/result","POST",{"task_id":task["task_id"],"ok":ok,"result":result})
        except Exception as e:
            with open(log,"a",encoding="utf-8") as f:f.write(f"{time.time()} {type(e).__name__}: {e}\n")
        time.sleep(INTERVAL)
