# Unified Agent Combat Cards Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the duplicated HUD Agents table with compact operational Combat Status cards and safely remove the stale live `eng-3` roster artifact.

**Architecture:** Keep the existing three authenticated reads and join them in the browser by `agent_id`. Render one card per current agent, enrich it with telemetry, and reuse existing attach/revive endpoints. Treat live roster cleanup as a separate digest-addressed operator transaction after the candidate passes isolated verification.

**Tech Stack:** Static HTML/CSS/JavaScript, Python `unittest` source contracts, Playwright browser journeys, Docker isolated verifier, PowerShell deployment transaction.

---

### Task 1: Define the unified-card contract

**Files:**
- Create: `verify/test_hud_unified_agent_cards.py`
- Modify: `verify/run-suite.sh`

- [ ] **Step 1: Write the failing source-contract tests**

```python
class HudUnifiedAgentCardsContract(unittest.TestCase):
    def test_agents_table_is_replaced_by_unified_cards(self):
        self.assertNotIn('id="agentsTable"', self.source)
        self.assertIn('function buildCardRows()', self.source)
        self.assertIn('function renderAgentCards()', self.source)

    def test_cards_attach_without_nested_action_bubbling(self):
        self.assertIn("card.dataset.attachUrl", self.source)
        self.assertIn("activateCardAttach", self.source)
        self.assertIn("event.stopPropagation()", self.source)
        self.assertIn("event.key==='Enter'||event.key===' '", self.source)

    def test_spawn_and_summary_are_compact(self):
        self.assertIn("Copy spawn", self.source)
        self.assertIn("summary-toggle", self.source)
        self.assertNotIn("class=\"cmd\"", self.source)
```

- [ ] **Step 2: Run the test and confirm RED**

Run: `python -m unittest verify.test_hud_unified_agent_cards -v`

Expected: failures for the existing `agentsTable`, missing card join, missing attach activation, and missing compact controls.

- [ ] **Step 3: Register the test in the isolated suite**

Add immediately after `test_scorpion_theme.py` in `verify/run-suite.sh` so both HUD contracts become part of the full gate:

```bash
python3 "$VERIFY/test_hud_provider_telemetry.py"
python3 "$VERIFY/test_hud_unified_agent_cards.py"
```

- [ ] **Step 4: Commit the red contract**

```bash
git add verify/test_hud_unified_agent_cards.py verify/run-suite.sh
git commit -m "test: define unified HUD agent cards"
```

### Task 2: Replace the duplicated table with operational cards

**Files:**
- Modify: `bin/dashboard.html`
- Test: `verify/test_hud_unified_agent_cards.py`
- Test: `verify/test_hud_provider_telemetry.py`

- [ ] **Step 1: Replace the Agents section markup**

Keep `#combatStatus` and `#telemetryCards`; remove the active `agentsTable` section. Convert retired history to a collapsed details element:

```html
<details id="retiredAgents" class="retired-agents">
  <summary>Retired engineers <span id="retiredCount">0</span></summary>
  <div id="retiredCards" class="retired-cards"></div>
</details>
```

- [ ] **Step 2: Build one joined view model per current agent**

Add a deterministic join:

```javascript
function buildCardRows(){
  const live=new Map(agents.map(row=>[row.agent_id,row]));
  const rosterMap=new Map(roster.filter(row=>!row.retired).map(row=>[row.agent_id,row]));
  const telemetry=telemetryMap();
  const ids=[...new Set([...live.keys(),...rosterMap.keys()])].sort();
  return ids.map(agentId=>({
    ...(rosterMap.get(agentId)||{}),
    ...(live.get(agentId)||{}),
    agent_id:agentId,
    telemetry:telemetry.get(agentId)||{}
  }));
}
```

- [ ] **Step 3: Add safe card attachment**

```javascript
function activateCardAttach(card){
  if(!card.dataset.attachUrl)return;
  window.open(card.dataset.attachUrl,'_blank','noopener,noreferrer');
}
function bindCardAttach(card,url){
  if(!url)return;
  card.dataset.attachUrl=url;
  card.tabIndex=0;
  card.setAttribute('role','link');
  card.onclick=()=>activateCardAttach(card);
  card.onkeydown=event=>{
    if(event.key==='Enter'||event.key===' '){event.preventDefault();activateCardAttach(card)}
  };
}
function stopCardAction(event){event.stopPropagation()}
```

- [ ] **Step 4: Render compact summary and lifecycle controls**

Use `textContent` exclusively. Limit the visible summary to 96 characters, add a `summary-toggle` button only when truncated, and give every nested button `onclick` handlers beginning with `event.stopPropagation()`. Render the full spawn command only into the clipboard action:

```javascript
const copy=el('button','card-action','Copy spawn');
copy.onclick=event=>{
  event.stopPropagation();
  navigator.clipboard?.writeText(row.spawn_cmd||'');
};
```

Alive cards expose `Attach`; dead non-retired cards expose a compact `Revive` action using the existing `/revive` POST body `{agent_id: row.agent_id}`.

- [ ] **Step 5: Preserve telemetry degradation**

Use `row.telemetry.health || {state:'unknown',stale:true}` and continue rendering roster lifecycle fields when `/todo/operator-telemetry` fails. The global LIVE badge becomes STALE but attach/revive remains available.

- [ ] **Step 6: Run focused tests and confirm GREEN**

Run:

```powershell
python -m unittest verify.test_hud_unified_agent_cards verify.test_hud_provider_telemetry verify.test_scorpion_theme verify.test_windows_dictation_only -v
```

Expected: all tests pass; no `innerHTML`, raw session ID, or diagnostic reference appears.

- [ ] **Step 7: Commit the card implementation**

```bash
git add bin/dashboard.html verify/test_hud_provider_telemetry.py
git commit -m "feat: unify HUD agent combat cards"
```

### Task 3: Verify browser interactions

**Files:**
- Modify: `verify/browser_journeys.js`
- Test: `verify/test_hud_unified_agent_cards.py`

- [ ] **Step 1: Add a browser journey for one-card-per-agent**

Seed Boss and Nightwatch, open `/dashboard`, and assert:

```javascript
await expect(page.locator('#telemetryCards .combat-card')).toHaveCount(2);
await expect(page.locator('#agentsTable')).toHaveCount(0);
```

- [ ] **Step 2: Prove nested actions do not attach**

Intercept popup creation, click `Copy spawn`, and assert no page opens. Then click the card body and assert the new page URL contains `/todo/terminal?agent=` and the encoded agent ID.

- [ ] **Step 3: Prove keyboard attachment and stale fallback**

Focus the Boss card, press Enter, and assert the same terminal URL. Abort `/todo/operator-telemetry`, repoll, and assert cards, lifecycle actions, and STALE badge remain visible.

- [ ] **Step 4: Run the focused browser journey**

Run the repository's existing browser-journey command from `verify/run-suite.sh` against the disposable runtime.

Expected: popup, keyboard, nested-action, and stale-fallback assertions pass.

- [ ] **Step 5: Commit browser coverage**

```bash
git add verify/browser_journeys.js verify/test_hud_unified_agent_cards.py
git commit -m "test: cover unified HUD card interactions"
```

### Task 4: Build and verify the packaged candidate

**Files:**
- No production file changes expected.

- [ ] **Step 1: Build from the current live base**

```powershell
$base=(docker inspect mypeople --format '{{.Config.Image}}').Trim()
docker build -f docker/Dockerfile.runtime-image --build-arg BASE_IMAGE=$base -t mypeople-node:unified-agent-cards .
```

- [ ] **Step 2: Run the complete isolated verifier**

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\verify\Invoke-IsolatedVerify.ps1 -Image mypeople-node:unified-agent-cards -TimeoutSeconds 1800 -UsePackagedSource
```

Expected: focused HUD contracts, browser journeys, Gate B, provider contracts, and J1-J52 all pass with exit 0.

- [ ] **Step 3: Record candidate evidence**

Capture the Git SHA, tree SHA, image ID, and verifier exit code in the final review message. Do not deploy yet.

### Task 5: Archive the ghost row and deploy after approval

**Files:**
- Runtime state only; no repository source changes.

- [ ] **Step 1: Archive the exact stale row privately**

Inside the container, lock `run/roster.json`, select only `node-1/main:eng-3`, write a mode-0600 timestamped archive under `run/roster-archive/`, record SHA-256, and abort unless exactly one dead non-retired row matches.

- [ ] **Step 2: Atomically remove only that row**

Write a temporary roster beside the source, fsync, replace atomically, and verify Boss/Nightwatch rows and their hashes are unchanged.

- [ ] **Step 3: Deploy backup-first**

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\windows\Upgrade-MyPeopleDockerImage.ps1 -CandidateImage mypeople-node:unified-agent-cards
```

- [ ] **Step 4: Run live smokes**

Assert Priorities and `/dashboard` return 200, exactly Boss/Nightwatch active cards exist, `eng-3` is absent, card click opens the terminal URL, nested actions do not open it, both providers remain alive, restart count is zero, and the Windows launcher reaches READY.

- [ ] **Step 5: Publish only the verified merged tree**

Merge after approval, rerun focused tests on main, push `main`, and verify `git ls-remote origin refs/heads/main` equals local HEAD.
