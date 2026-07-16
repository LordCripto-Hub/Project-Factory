const assert = require('assert');
const fs = require('fs');
const path = require('path');

const modulePath = path.join(__dirname, 'browser_error_filter.js');
assert.ok(fs.existsSync(modulePath), 'browser error filter module must exist');

const { shouldIgnoreConsoleError } = require(modulePath);

assert.strictEqual(
  shouldIgnoreConsoleError(
    '[ttyd] fetch http://127.0.0.1:7682/token: TypeError: Load failed',
    'webkit',
  ),
  true,
);
assert.strictEqual(
  shouldIgnoreConsoleError(
    '[ttyd] fetch http://127.0.0.1:7682/token: TypeError: Load failed',
    'chromium',
  ),
  false,
);
assert.strictEqual(
  shouldIgnoreConsoleError('beforeunload confirmation panel was suppressed', 'webkit'),
  true,
);
assert.strictEqual(
  shouldIgnoreConsoleError('application crashed with Load failed', 'webkit'),
  false,
);
assert.strictEqual(
  shouldIgnoreConsoleError('/127.0.0.1:35861/todo/board due to access control checks.', 'webkit', true),
  true,
);
assert.strictEqual(
  shouldIgnoreConsoleError('/127.0.0.1:35861/todo/board due to access control checks.', 'webkit'),
  false,
);
assert.strictEqual(
  shouldIgnoreConsoleError('/127.0.0.1:35861/todo/board due to access control checks.', 'chromium', true),
  false,
);
assert.strictEqual(
  shouldIgnoreConsoleError('/127.0.0.1:35861/todo/proof due to access control checks.', 'webkit', true),
  false,
);

const journey = fs.readFileSync(path.join(__dirname, 'browser_journeys.js'), 'utf8');
assert.match(journey, /const liveMarker = `browser-\$\{browserName\}-\$\{Date\.now\(\)\}`;/);
assert.ok(journey.includes("await page.fill('#commentInput', `browser comment ${liveMarker}`);"));
assert.ok(journey.includes("getByText(`browser comment ${liveMarker}`, { exact: true })"));
assert.ok(journey.includes("page.on('framenavigated'"));
assert.ok(journey.includes('boardPollNavigation.defer(e.message);'));
assert.ok(journey.includes('await boardPollNavigation.verify(page);'));

console.log('browser console error filter: ok');
