#!/bin/bash
set -euo pipefail
ROOT=${INSTALL_DIR:-$HOME/mypeople}; mkdir -p "$ROOT"/{bin,run/boss,run/eng,status,todos,plugins} "$HOME/.local/bin" "$HOME/.claude"
python3 - "$ROOT" <<'PY'
import json,os,sys
root=os.path.realpath(sys.argv[1]);p=os.path.expanduser('~/.claude.json')
try:d=json.load(open(p))
except:d={}
d.update(hasCompletedOnboarding=True,lastOnboardingVersion=d.get('lastOnboardingVersion','2.0.0'),theme=d.get('theme','dark'));projects=d.setdefault('projects',{})
for x in (os.path.expanduser('~'),root,root+'/run',root+'/run/eng',root+'/run/boss',root+'/bin',root+'/run/nightwatch'):projects.setdefault(os.path.realpath(x),{})['hasTrustDialogAccepted']=True
t=p+'.tmp';json.dump(d,open(t,'w'),indent=2);os.replace(t,p)
p=os.path.expanduser('~/.claude/settings.json')
try:d=json.load(open(p))
except:d={}
d['skipDangerousModePermissionPrompt']=True;t=p+'.tmp';json.dump(d,open(t,'w'),indent=2);os.replace(t,p)
PY
ln -sf "$ROOT/bin/mp" "$HOME/.local/bin/mp"; ln -sf "$ROOT/bin/mypeople" "$HOME/.local/bin/mypeople"
chmod +x "$ROOT"/bin/* "$ROOT"/plugins/tmux-boss-hooks/scripts/emit-event
tmux source-file "$HOME/.tmux.conf" 2>/dev/null || true
