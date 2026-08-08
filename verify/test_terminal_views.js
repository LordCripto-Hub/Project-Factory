const { chromium } = require('playwright');
const http = require('http');
const fs = require('fs');
const path = require('path');

let base = process.env.MP_VERIFY_BASE_URL || '';
const agent = {
  agent_id: 'node-1/main:Boss', target: 'mc-main:Boss', state: 'working',
  cols: 120, rows: 36, read_port: 7682, write_port: 7681, is_master: true, boss_id: '',
};

function size(page, selector) {
  return page.locator(selector).first().evaluate(el => {
    const r = el.getBoundingClientRect();
    const frame = el.querySelector('iframe');
    return [r.width, r.height, frame?.getBoundingClientRect().width, frame?.getBoundingClientRect().height];
  });
}

async function check(page, name, selector, getPollCount) {
  await page.goto(`${base}/terminal-graph`);
  await page.waitForSelector(`${selector} iframe`);
  const before = await size(page, selector);
  for (let i = 0; i < 8; i++) {
    await page.evaluate(() => window.__graph.poll());
  }
  const after = await size(page, selector);
  if (JSON.stringify(before) !== JSON.stringify(after)) {
    throw new Error(`${name} terminal viewport changed: ${before} -> ${after}`);
  }
  if (getPollCount() < 2) throw new Error(`${name} regression did not exercise changing geometry`);
  if (name === 'Graph') {
    await page.waitForSelector('.graph-topbar');
    await page.waitForSelector('[data-layer="agents"]');
    if (await page.locator('path[data-kind="ASSIGNS"]').count() < 1) {
      throw new Error('Graph semantic ASSIGNS edge missing');
    }
    await page.locator('.task-node').first().click();
    await page.waitForSelector('.inspector-content');
  }
  console.log(`${name} stable: ${after.join('x')}`);
}

(async () => {
  let fixtureServer;
  if (!base) {
    fixtureServer = http.createServer((req, res) => {
      const requestPath = (req.url || '').split('?')[0];
      const files = {
        '/terminal-graph': path.join(__dirname, '..', 'bin', 'terminal-graph.html'),
        '/wall': path.join(__dirname, '..', 'bin', 'wall.html'),
        '/assets/mypeople-ui.css': path.join(__dirname, '..', 'bin', 'mypeople-ui.css'),
        '/assets/graph-canvas.css': path.join(__dirname, '..', 'bin', 'graph-canvas.css'),
      };
      const file = files[requestPath];
      if (!file) { res.writeHead(404); res.end('not found'); return; }
      res.writeHead(200, { 'Content-Type': file.endsWith('.css') ? 'text/css' : 'text/html' });
      res.end(fs.readFileSync(file));
    });
    await new Promise(resolve => fixtureServer.listen(0, '127.0.0.1', resolve));
    base = 'http://127.0.0.1:' + fixtureServer.address().port;
  }
 const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage({ viewport: { width: 1440, height: 1080 } });
  let graphCalls = 0;
  await page.route('**/todo/terminal-graph', route => {
    graphCalls++;
    const boss = { ...agent, role: 'boss', summary: 'command node', backend: 'codex' };
    const nightwatch = { agent_id: 'node-1/nightwatch:Nightwatch', target: 'mc-nightwatch:Nightwatch', state: 'idle', status: 'idle', cols: 120 + graphCalls * 17, rows: 36 + graphCalls * 5, read_port: 7682, write_port: 7681, role: 'nightwatch', boss_id: boss.agent_id, summary: 'oversight', backend: 'codex' };
    const worker = { agent_id: 'node-1/eng:Worker', target: 'mc-eng:Worker', state: 'working', status: 'working', cols: 120 + graphCalls * 17, rows: 36 + graphCalls * 5, read_port: 7682, write_port: 7681, role: 'worker', boss_id: boss.agent_id, summary: 'build', backend: 'codex' };
    const task = { id: 'graph-task', title: 'Prepare release evidence', state: 'review', card_kind: 'REVIEW', assignee: worker.agent_id, owner_live: true, proof_count: 1, evidence_policy: 'required', done_condition: 'Evidence attached', project_slug: 'graph' };
    route.fulfill({ contentType: 'application/json', body: JSON.stringify({ agents: [boss, nightwatch, worker], edges: [{ parent: boss.agent_id, child: nightwatch.agent_id, kind: 'OBSERVES' }, { parent: boss.agent_id, child: worker.agent_id, kind: 'ASSIGNS' }], tasks: [task], states: [] }) });
  });
  await page.route('**/todo/board', route => route.fulfill({ contentType: 'application/json', body: JSON.stringify({ tasks: { 'graph-task': { id: 'graph-task', text: 'Prepare release evidence', state: 'review', assignee: 'node-1/eng:Worker', doneCondition: 'Evidence attached', comments: [], proofs: [{ kind: 'text', body: 'fixture' }] } } }) }));
  await check(page, 'Graph', '.node', () => graphCalls);
  if (process.env.MP_GRAPH_SCREENSHOT) await page.screenshot({ path: process.env.MP_GRAPH_SCREENSHOT, fullPage: true });
  await browser.close();
  if (fixtureServer) await new Promise(resolve => fixtureServer.close(resolve));
})().catch(error => { console.error(error); process.exit(1); });
