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

console.log('browser console error filter: ok');
