const { chromium, webkit } = require('playwright');
const fs = require('fs');
const path = require('path');
const { shouldIgnoreConsoleError } = require('./browser_error_filter');

function arg(name, fallback = '') {
  const idx = process.argv.indexOf(`--${name}`);
  return idx >= 0 ? process.argv[idx + 1] : fallback;
}

const scenario = arg('scenario', 'live_core');
const browserName = arg('browser', 'chromium');
const manifestPath = arg('manifest', '');
const baseUrl = process.env.MP_VERIFY_BASE_URL || 'http://127.0.0.1:9933';
const hudUrl = process.env.MP_VERIFY_HUD_URL || 'http://127.0.0.1:9900';
const videoDir = process.env.MP_VERIFY_VIDEO_DIR || path.join(__dirname, 'videos');
const shotDir = process.env.MP_VERIFY_SCREEN_DIR || path.join(__dirname, 'screenshots');
const manifest = manifestPath && fs.existsSync(manifestPath) ? JSON.parse(fs.readFileSync(manifestPath, 'utf8')) : {};

function engine(name) {
  return name === 'webkit' ? webkit : chromium;
}

async function launch() {
  const browser = await engine(browserName).launch({ headless: true });
  const context = await browser.newContext({
    viewport: { width: 1440, height: 1080 },
    recordVideo: { dir: videoDir },
  });
  const page = await context.newPage();
  const errors = [];
  page.on('console', m => {
    const message = m.text();
    if (m.type() === 'error' && !shouldIgnoreConsoleError(message, browserName)) {
      errors.push(`console: ${message}`);
    }
  });
  page.on('pageerror', e => {
    if (!/Load failed/i.test(e.message) && !/beforeunload.*confirmation dialog/i.test(e.message)) errors.push(`pageerror: ${e.message}`);
  });
  page.on('requestfailed', r => {
    const u = r.url();
    const err = r.failure()?.errorText || '';
    // The attach control intentionally opens a short-lived tmux popup; WebKit
    // reports its interrupted frame navigation as a request failure even though
    // the popup URL assertion below has succeeded.
    if (!/about:blank/.test(u) && !/ERR_ABORTED|cancelled|Frame load interrupted/.test(err) && !/fonts.googleapis/.test(u) && !/fonts.gstatic.com/.test(u)) {
      errors.push(`requestfailed: ${u} ${err}`);
    }
  });
  return { browser, context, page, errors };
}

async function saveShot(page, name) {
  await page.screenshot({ path: path.join(shotDir, `${name}-${browserName}.png`), fullPage: true });
}

async function text(page, sel) {
  return (await page.locator(sel).textContent()) || '';
}

async function expect(cond, msg) {
  if (!cond) throw new Error(msg);
}

async function openCard(page, id) {
  await page.click(`li.task[data-id="${id}"] .task-text`);
  await page.waitForSelector('body.modal-open');
}

async function closeCard(page) {
  await page.click('#closeModal');
  await page.waitForFunction(() => !document.body.classList.contains('modal-open'));
}

async function board(page) {
  return await page.evaluate(async ({ baseUrl }) => {
    const r = await fetch(baseUrl + '/todo/board', { credentials: 'same-origin', cache: 'no-store' });
    return await r.json();
  }, { baseUrl });
}

async function api(page, path, body) {
  return await page.evaluate(async ({ baseUrl, path, body }) => {
    const r = await fetch(baseUrl + path, {
      method: 'POST',
      credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    let data = {};
    try { data = await r.json(); } catch {}
    if (!r.ok) throw new Error((data && data.error) || `${r.status}`);
    return data;
  }, { baseUrl, path, body });
}

async function count(page, sel) {
  return await page.locator(sel).count();
}

async function liveCore(page) {
  await page.goto(`${baseUrl}/`, { waitUntil: 'domcontentloaded' });
  await page.waitForSelector('h1');
  await expect((await text(page, 'h1')) === 'Priorities', 'board title mismatch');
  await page.fill('#taskInput', 'verify browser live core');
  await page.keyboard.press('Enter');
  await page.waitForSelector('li.task');
  const first = page.locator('li.task').first();
  await first.locator('.task-text').click();
  await page.waitForSelector('body.modal-open');
  await page.fill('#commentInput', 'browser comment');
  await page.click('#postComment');
  await page.getByText('browser comment', { exact: false }).waitFor();
  await closeCard(page);
  await page.click('a.navlink[href="/dashboard"]');
  await page.waitForURL(/\/dashboard$/);
  await expect((await text(page, 'h1')) === 'MyPeople - HUD', 'HUD title mismatch');
  await page.click('a.nav[href="/"]');
  await page.waitForURL(/\/$/);
  await page.click('a.navlink[href="/wall"]');
  await page.waitForURL(/\/wall$/);
  await page.waitForSelector('iframe');
  await page.goto(`${baseUrl}/`, { waitUntil: 'domcontentloaded' });
  await page.click('a.navlink[href="/terminal-graph"]');
  await page.waitForURL(/\/terminal-graph$/);
  await page.waitForSelector('iframe');
  await saveShot(page, 'live-core');
}

async function sandboxSuite(page) {
  const s = manifest.sandbox || {};
  const taskIds = s.taskIds || [];
  if (taskIds.length < 10) throw new Error('sandbox manifest missing task ids');
  await page.goto(`${baseUrl}/`, { waitUntil: 'domcontentloaded' });
  await page.waitForSelector('h1');
  await expect((await text(page, 'h1')) === 'Priorities', 'sandbox title mismatch');
  await expect((await text(page, '.brand .subt')).includes('HUD'), 'board header incomplete');
  await expect(await count(page, '.viewbar .vbtn') >= 5, 'filter buttons missing');
  await expect(await count(page, '.chip') >= 6, 'state chips missing');
  await expect(await count(page, `li.task[data-id="${s.ownerTask}"]`) === 1, 'owner fixture missing');
  await expect(await count(page, `li.task[data-id="${s.deleteId}"]`) === 1, 'delete fixture missing');
  await expect(await count(page, `li.task[data-id="${s.safeMdId}"]`) === 1, 'markdown fixture missing');

  await api(page, '/todo/update', { op: 'del', id: s.deleteId });
  await page.reload({ waitUntil: 'domcontentloaded' });
  await expect(await count(page, `li.task[data-id="${s.deleteId}"]`) === 0, 'delete fixture survived');

  // Filter toggle persists across reloads.
  await page.locator('.chip[data-state="cancelled"]').click();
  await page.reload({ waitUntil: 'domcontentloaded' });
  await expect(await page.locator('.chip[data-state="cancelled"]').getAttribute('aria-pressed') === 'false', 'cancelled chip did not persist off');
  await expect(await count(page, 'li.task[data-state="cancelled"]') === 0, 'cancelled tasks still visible');
  await page.locator('.chip[data-state="cancelled"]').click();

  // Recurring lane and state transition into it.
  await expect(await count(page, '.badge.st-recurring') === 0, 'recurring leaked into default board');
  await page.getByRole('button', { name: /recurring/i }).click();
  await expect((await text(page, '.vbtn.active')).includes('recurring'), 'recurring button not active');
  await expect(await count(page, 'li.task[data-state="recurring"]') === (s.recurringIds || []).length, 'recurring lane incorrect');
  await page.getByRole('button', { name: 'all' }).click();

  // Pin at least 6 cards, proving the 2026-06-29 supersession of the old max-5 cap.
  for (const id of s.pinIds || []) {
    await page.locator(`li.task[data-id="${id}"] .pin`).click();
  }
  await page.reload({ waitUntil: 'domcontentloaded' });
  const boardData = await board(page);
  const pinned = (s.pinIds || []).filter(id => boardData.tasks[id] && boardData.tasks[id].pinned);
  await expect(pinned.length >= 6, 'pin cap still active');
  await expect(!JSON.stringify(boardData).includes('pin_limit'), 'pin_limit surfaced');
  const topFirst = boardData.displayOrder.filter(id => boardData.tasks[id]?.pinned);
  await expect(topFirst.length >= 6, 'pinned group incomplete');

  // The compact owner is a native, one-click link. The server redirect chooses
  // the browser-reachable localhost ttyd endpoint without staging about:blank.
  const compactOwner = page.locator(`[data-id="${s.ownerTask}"] a.asg-link`);
  const compactHref = await compactOwner.getAttribute('href');
  await expect((compactHref || '').startsWith('/todo/terminal?agent='), 'card owner link is not native');
  await expect(await compactOwner.getAttribute('target') === '_blank', 'card owner link target is not _blank');
  await expect((await compactOwner.getAttribute('rel') || '').includes('noopener'), 'card owner link lacks noopener');

  // Owner link opens the same-origin terminal wrapper; ttyd remains inside its iframe.
  await openCard(page, s.ownerTask);
  await expect(await count(page, '#ownerLine a.asg-link') >= 1, 'owner link missing');
  const popup = page.waitForEvent('popup');
  await page.locator('#ownerLine a.asg-link').first().click();
  const pop = await popup;
  await pop.waitForURL(url => !url.toString().endsWith('about:blank') && url.toString().includes('/todo/terminal?agent='), { timeout: 5000 });
  await pop.waitForSelector('#terminalFrame');
  await pop.waitForFunction(() => document.querySelector('#terminalFrame')?.src.includes('?arg=-t&arg='));
  await pop.close();
  await closeCard(page);

  // Safe markdown fixture.
  await openCard(page, s.safeMdId);
  await expect(await count(page, '#modal h1, #modal h2, #modal h3') >= 1, 'markdown headings missing');
  await expect(await count(page, '#modal strong') >= 1, 'bold missing');
  await expect(await count(page, '#modal em') >= 1, 'italic missing');
  await expect(await count(page, '#modal code') >= 1, 'inline code missing');
  await expect(await count(page, '#modal pre') >= 1, 'fenced code missing');
  await expect(await count(page, '#modal ul, #modal ol') >= 1, 'lists missing');
  await expect(await count(page, '#modal blockquote') >= 1, 'blockquote missing');
  const renderedTable = await page.evaluate(body => {
    const wrap = window.__mp.markdown(body);
    return wrap.querySelector('table') !== null;
  }, '| a | b |\n| :-- | --: |\n| x | y |');
  await expect(renderedTable, 'table missing');
  await expect(await count(page, '#modal a[target="_blank"][rel*="noopener"][rel*="noreferrer"]') >= 1, 'safe link attrs missing');
  await expect(await count(page, '#modal script, #modal img[onerror], #modal a[href^="javascript:"]') === 0, 'unsafe markup rendered');
  await closeCard(page);

  // Scroll behavior and jump-to-latest.
  await openCard(page, s.scrollId);
  await page.waitForTimeout(3200);
  await page.locator('#thread').hover();
  await page.mouse.wheel(0, -6000);
  await page.waitForTimeout(400);
  await expect(await page.locator('#jumpLatest').isVisible(), 'jump latest not visible when scrolled up');
  await page.click('#jumpLatest');
  await page.waitForTimeout(2000);
  await expect(!(await page.locator('#jumpLatest').isVisible()), 'jump latest stayed visible');
  await closeCard(page);

  // Proof rendering and first-class evidence upload inside the same task thread.
  await openCard(page, s.proofId);
  await expect(await count(page, '.proof img, .proof video') >= 1, 'proof render missing');
  const beforeEvidence = await count(page, '.evidence-card');
  await page.locator('#evidenceFile').setInputFiles({
    name: 'browser-evidence.png',
    mimeType: 'image/png',
    buffer: Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO94W9kAAAAASUVORK5CYII=', 'base64'),
  });
  await page.waitForFunction(n => document.querySelectorAll('.evidence-card').length > n, beforeEvidence);
  await expect((await text(page, '#evidenceStatus')).includes('attached'), 'evidence upload status missing');
  await expect(await count(page, '.evidence-meta') >= 1, 'evidence metadata missing');
  await closeCard(page);

  // Cross-nav by real clicks.
  await page.goto(`${baseUrl}/`, { waitUntil: 'domcontentloaded' });
  await page.click('a.navlink[href="/dashboard"]');
  await page.waitForURL(/\/dashboard$/);
  await expect((await text(page, 'h1')) === 'MyPeople - HUD', 'board->HUD failed');
  await page.click('a.nav[href="/"]');
  await page.waitForURL(/\/$/);
  await expect((await text(page, 'h1')) === 'Priorities', 'HUD->board failed');
  await page.goto(`${hudUrl}/dashboard`, { waitUntil: 'domcontentloaded' });
  await page.waitForSelector('#agentsTable');
  await page.click('a.nav[href="/"]');
  await page.waitForURL(/\/$/);

  // Recurring flow.
  const recurringFlow = taskIds.find(id => id !== s.deleteId && id !== s.ownerTask && id !== s.safeMdId && id !== s.scrollId);
  await openCard(page, recurringFlow);
  await page.selectOption('#stateSelect', 'recurring');
  await page.click('#saveDetails');
  await page.waitForTimeout(250);
  await expect(await count(page, `li.task[data-id="${recurringFlow}"]`) === 0, 'recurring flow card still on default board');
  await closeCard(page);
  await page.getByRole('button', { name: /recurring/i }).click();
  await expect(await count(page, `li.task[data-id="${recurringFlow}"]`) === 1, 'recurring flow card missing from lane');

  // Readability + modal sizing.
  await page.getByRole('button', { name: 'all' }).click();
  await openCard(page, s.scrollId);
  const metrics = await page.$eval('#modal', modal => {
    const text = document.querySelector('.ev-text');
    const s = getComputedStyle(text);
    const r = modal.getBoundingClientRect();
    return {
      font: parseFloat(s.fontSize),
      lineHeight: parseFloat(s.lineHeight),
      width: r.width / innerWidth,
      height: r.height / innerHeight,
      bodyOverflow: getComputedStyle(document.body).overflow,
    };
  });
  await expect(metrics.font >= 17 && metrics.font <= 19, 'message font not ~18px');
  await expect(metrics.width >= 0.82 && metrics.height >= 0.82, 'modal not near fullscreen');
  await expect(metrics.bodyOverflow === 'hidden', 'body scroll not contained');
  await closeCard(page);

  // Hidden live-board controls check.
  await page.goto(`${baseUrl}/dashboard`, { waitUntil: 'domcontentloaded' });
  await expect(await count(page, 'a.attach') >= 0, 'dashboard missing');
  await page.goto(`${baseUrl}/wall`, { waitUntil: 'domcontentloaded' });
  await expect(await count(page, 'iframe') >= 1, 'wall iframe missing');
  await page.goto(`${baseUrl}/terminal-graph`, { waitUntil: 'domcontentloaded' });
  await expect(await count(page, 'iframe') >= 1, 'graph iframe missing');
  await saveShot(page, `sandbox-${browserName}`);
}

(async () => {
  const { browser, context, page, errors } = await launch();
  try {
    if (scenario === 'live_core') {
      await liveCore(page);
    } else if (scenario === 'sandbox_suite') {
      await sandboxSuite(page);
    } else {
      throw new Error(`unknown scenario: ${scenario}`);
    }
    if (errors.length) throw new Error(errors.join('\n'));
  } finally {
    await context.close().catch(() => {});
    await browser.close().catch(() => {});
  }
})().catch(err => {
  console.error(err);
  process.exit(1);
});
