const { chromium } = require('playwright');

const base = process.env.MP_VERIFY_BASE_URL || 'http://127.0.0.1:9933';
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
  await page.goto(`${base}/${name === 'Wall' ? 'wall' : 'terminal-graph'}`);
  await page.waitForSelector(`${selector} iframe`);
  const before = await size(page, selector);
  for (let i = 0; i < 8; i++) {
    await page.evaluate(mode => mode === 'wall' ? window.__wall.poll() : window.__graph.poll(), name === 'Wall' ? 'wall' : 'graph');
  }
  const after = await size(page, selector);
  if (JSON.stringify(before) !== JSON.stringify(after)) {
    throw new Error(`${name} terminal viewport changed: ${before} -> ${after}`);
  }
  if (getPollCount() < 2) throw new Error(`${name} regression did not exercise changing geometry`);
  console.log(`${name} stable: ${after.join('x')}`);
}

(async () => {
  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage({ viewport: { width: 1440, height: 1080 } });
  let wallCalls = 0;
  await page.route('**/todo/wall', route => {
    wallCalls++;
    route.fulfill({ contentType: 'application/json', body: JSON.stringify([{ ...agent, cols: 120 + wallCalls * 17, rows: 36 + wallCalls * 5 }]) });
  });
  await check(page, 'Wall', '.tile', () => wallCalls);

  let graphCalls = 0;
  await page.route('**/todo/terminal-graph', route => {
    graphCalls++;
    route.fulfill({ contentType: 'application/json', body: JSON.stringify({ agents: [{ ...agent, cols: 120 + graphCalls * 17, rows: 36 + graphCalls * 5 }], edges: [], tasks: [], states: [] }) });
  });
  await page.route('**/todo/board', route => route.fulfill({ contentType: 'application/json', body: JSON.stringify({ tasks: {} }) }));
  await check(page, 'Graph', '.node', () => graphCalls);
  await browser.close();
})().catch(error => { console.error(error); process.exit(1); });
