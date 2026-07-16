#!/usr/bin/env python3
"""Read-only live-board exporter into an isolated, per-instance git repository."""
from __future__ import annotations
import argparse, hashlib, json, os, pathlib, shutil, subprocess, sys, time
from mpcommon import ENV, ROOT, load_json

def default_repo(root=ROOT,port=None,host=None):
    port=str(port or ENV.get("TODO_PORT","9933"));host=host or ENV.get("HOST_ID","node")
    discriminator=f"{port}-{hashlib.sha1(os.path.realpath(root).encode()).hexdigest()[:8]}"
    return os.path.expanduser(f"~/.mypeople/board-backup/{host}-{discriminator}")
def run(repo,*args,check=True,capture=False):
    return subprocess.run(["git","-C",repo,*args],check=check,text=True,capture_output=capture)
def count(board):return len(board.get("tasks",{})) if isinstance(board,dict) else 0
def canonical(board):return json.dumps(board,ensure_ascii=False,sort_keys=True,indent=2)+"\n"
def lineage_proven(head, board):
    """Return evidence that a smaller board belongs to a new lineage.

    A deleted-task archive plus zero shared live IDs is strong evidence that
    HEAD is a stale fixture/import baseline, not a live predecessor.  It is
    intentionally only a diagnostic; recovery still requires an explicit
    operator command.
    """
    if not isinstance(head,dict) or not isinstance(board,dict): return False
    old=set((head.get("tasks") or {}).keys())
    current=set((board.get("tasks") or {}).keys())
    return bool(board.get("deletedTasks")) and bool(old) and not (old & current)

def recover_baseline(board_path, repo, reason):
    """Explicitly accept the live board as the next export baseline.

    The old canonical snapshot remains in Git history and the commit records
    the operator-supplied provenance reason.  No daemon path calls this.
    """
    if not str(reason or "").strip(): raise ValueError("recovery_reason_required")
    board=load_json(os.path.realpath(board_path),None)
    if not isinstance(board,dict): raise RuntimeError("live board is empty or invalid")
    repo=os.path.realpath(repo);os.makedirs(repo,exist_ok=True)
    if not os.path.isdir(os.path.join(repo,".git")):
        subprocess.run(["git","init","-q",repo],check=True);run(repo,"config","user.email","mypeople@localhost");run(repo,"config","user.name","MyPeople Board Exporter")
    head=run(repo,"show","HEAD:board.v2.json",check=False,capture=True)
    old=json.loads(head.stdout) if head.returncode==0 else None
    if old is not None and not lineage_proven(old,board):
        raise RuntimeError("baseline_provenance_insufficient")
    pathlib.Path(os.path.join(repo,"board.v2.json")).write_text(canonical(board),encoding="utf-8")
    audit={"recoveredAt":time.time(),"reason":str(reason).strip(),"previousTaskCount":count(old or {}),"acceptedTaskCount":count(board)}
    pathlib.Path(os.path.join(repo,"board.v2.json.BASELINE_RECOVERY.json")).write_text(canonical(audit),encoding="utf-8")
    run(repo,"add","board.v2.json","board.v2.json.BASELINE_RECOVERY.json");run(repo,"commit","-q","-m","recover board export baseline")
    return "baseline_recovered"
def export_once(board_path,repo):
    board_path=os.path.realpath(board_path);repo=os.path.realpath(repo);board=load_json(board_path,None)
    if not isinstance(board,dict):raise RuntimeError("live board is empty or invalid")
    os.makedirs(repo,exist_ok=True)
    if not os.path.isdir(os.path.join(repo,".git")):
        subprocess.run(["git","init","-q",repo],check=True);run(repo,"config","user.email","mypeople@localhost");run(repo,"config","user.name","MyPeople Board Exporter")
    head=None
    p=run(repo,"show","HEAD:board.v2.json",check=False,capture=True)
    if p.returncode==0:
        try:head=json.loads(p.stdout)
        except:head=None
    if head is not None and count(head)>5 and count(board)<count(head)*.5:
        previous=run(repo,"log","-1","--format=%s",check=False,capture=True).stdout.strip()
        name=f"board.v2.json.SUSPECT.{time.time_ns()}";path=os.path.join(repo,name);pathlib.Path(path).write_text(canonical(board),encoding="utf-8")
        run(repo,"add",name);run(repo,"commit","-q","-m",f"quarantine catastrophic shrink ({count(board)}/{count(head)})")
        # Keep one alert per shrink episode.  The quarantine commit itself is
        # durable evidence across exporter restarts; a later canonical commit
        # resets the episode.
        already_quarantined=previous.startswith("quarantine catastrophic shrink")
        if os.environ.get("MYPEOPLE_SUPPRESS_BOSS_NOTIFY")!="1" and not already_quarantined:
            subprocess.run([os.path.join(ROOT,"bin","mp"),"send",ENV.get("BOSS_AGENT","main:Boss"),f"[board-export] catastrophic shrink quarantined: {name}"],check=False)
        return "quarantined"
    target=os.path.join(repo,"board.v2.json");pathlib.Path(target).write_text(canonical(board),encoding="utf-8")
    run(repo,"add","board.v2.json")
    diff=run(repo,"diff","--cached","--quiet",check=False)
    if diff.returncode:run(repo,"commit","-q","-m",f"board snapshot {int(time.time())}");return "committed"
    return "unchanged"
def main():
    ap=argparse.ArgumentParser();ap.add_argument("--once",action="store_true");ap.add_argument("--print-repo",action="store_true");ap.add_argument("--recover-baseline",action="store_true");ap.add_argument("--reason",default="");ap.add_argument("--interval",type=float,default=2);a=ap.parse_args()
    board=os.path.realpath(os.environ.get("BOARD_PATH",os.path.join(ROOT,"todos","board.v2.json")));repo=os.path.realpath(os.environ.get("EXPORT_REPO",ENV.get("EXPORT_REPO") or default_repo()))
    if a.print_repo:print(repo);return
    if a.recover_baseline:print(recover_baseline(board,repo,a.reason));return
    if a.once:print(export_once(board,repo));return
    sig=None
    while True:
        try:
            st=os.stat(board);new=(st.st_mtime_ns,st.st_size)
            if new!=sig:export_once(board,repo);sig=new
        except Exception as e:print(f"board-export: {e}",file=sys.stderr)
        time.sleep(a.interval)
if __name__=="__main__":main()
