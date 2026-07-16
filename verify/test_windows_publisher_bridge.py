#!/usr/bin/env python3
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
windows = (ROOT / "windows" / "Publish-MyPeopleProject.ps1").read_text(encoding="utf-8")
wrapper = (ROOT / "bin" / "publish-with-credential").read_text(encoding="utf-8")
askpass = (ROOT / "bin" / "mypeople-git-askpass").read_text(encoding="utf-8")

assert "[switch]$CheckOnly" in windows
assert "git credential fill" in windows
assert "System.Diagnostics.ProcessStartInfo" in windows
assert "$env:ComSpec" in windows
assert "RedirectStandardOutput" in windows
assert "[System.IO.File]::WriteAllText" in windows
assert "[System.Text.Encoding]::ASCII" in windows
assert "Remove-Item -LiteralPath" in windows
assert "$credentialRequest | & git credential fill" not in windows
assert "docker exec -i mypeople" in windows
assert "publish-with-credential" in windows
assert "protocol=https" in windows
assert "host=github.com" in windows
assert "Write-Output $credential" not in windows
assert "Write-Host $credential" not in windows
assert "MYPEOPLE_GIT_PASSWORD" in wrapper
assert "GIT_ASKPASS" in wrapper
assert "json.load(sys.stdin)" in wrapper
assert "MYPEOPLE_GIT_USERNAME" in askpass
assert "MYPEOPLE_GIT_PASSWORD" in askpass
assert "set -x" not in askpass
assert "print(payload)" not in wrapper
assert "print(secret)" not in wrapper

print("PASS transient Windows credential bridge contract")
