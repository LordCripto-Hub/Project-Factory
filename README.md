# Project Factory - MyPeople with Codex

MyPeople is a local coordination environment for Codex agents running through Docker and tmux. It provides a Boss, Nightwatch, delegated workers, Priorities, and an operational HUD.

This repository contains only the installable product: source code, documentation, plugins, Windows launchers, and verification. Live runtime state is intentionally excluded from version control.

Provenance: this implementation was generated and hardened from the public `delattre1/plow-seedlab-mypeople` seed. The seed does not declare a license, so this repository does not imply or add one.

## Runtime state excluded from Git

- `run/`, `status/`, and `todos/`
- Codex or Claude sessions
- recordings and screenshots
- `.env` files, tokens, keys, and credentials
- `node_modules/` and generated test artifacts

## Quick start inside Linux or Docker

```bash
export INSTALL_DIR=/home/mp/mypeople
bash install.sh
mypeople up --detach
mp status
```

Default interfaces:

- Priorities: <http://localhost:9933/>
- Wall: <http://localhost:9933/wall>
- Terminal Graph: <http://localhost:9933/terminal-graph>
- HUD: <http://localhost:9900/dashboard>
- Writable terminal: <http://localhost:7681/>
- Read-only terminal: <http://localhost:7682/>

Windows operators can install the desktop shortcut with:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\windows\Install-MyPeopleShortcut.ps1
```

The installer copies the launcher to `%LOCALAPPDATA%\MyPeople\launcher`, so the desktop shortcut does not depend on the repository remaining in its original directory.

## Documentation

- [User manual](docs/USER-MANUAL.md)
- [Minimal architecture](docs/MINIMAL-ARCHITECTURE.md)
- [Voice Dock](docs/VOICE-DOCK.md)

## Memory boundary

MyPeople is an execution plane, not another memory system. Each task receives one compact, explicit context packet. External knowledge systems may help compile that packet, but MyPeople does not query several memory layers automatically.
