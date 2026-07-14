'use strict';

function shouldIgnoreConsoleError(message, browserName) {
  const text = String(message || '');
  if (/beforeunload.*confirmation panel/i.test(text)) return true;
  return browserName === 'webkit'
    && /^\[ttyd\] fetch http:\/\/(?:127\.0\.0\.1|localhost):\d+\/token:\s+TypeError:\s+Load failed$/i.test(text);
}

module.exports = { shouldIgnoreConsoleError };