const assert = require('assert');
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const root = path.resolve(__dirname, '..');
const source = fs.readFileSync(path.join(root, 'bin', 'todos.html'), 'utf8');

function extract(pattern, name) {
  const match = source.match(pattern);
  assert(match, `${name} missing from Priorities`);
  return match[0];
}

const context = {
  URL,
  location: { href: 'http://127.0.0.1:9933/' },
};
vm.createContext(context);
const safeMarkdownHref = extract(
  /function safeMarkdownHref\(href\)\{try\{.*?\}catch\{return''\}\}/,
  'safeMarkdownHref',
);
const isDirectUrl = extract(
  /function isDirectUrl\(value\)\{[^}]+\}/,
  'isDirectUrl',
);
vm.runInContext(`${safeMarkdownHref};${isDirectUrl}`, context);

assert.strictEqual(context.isDirectUrl('browser comment'), '');
assert.strictEqual(context.isDirectUrl('/relative/path'), '');
assert.strictEqual(context.isDirectUrl('https://example.test/result'), 'https://example.test/result');
assert.strictEqual(context.isDirectUrl('http://127.0.0.1:9933/result'), 'http://127.0.0.1:9933/result');

assert(!source.includes("localStorage.setItem('mp_states',JSON.stringify([...enabled]))"));
assert(source.includes("enabled.has(x.dataset.state)?enabled.delete(x.dataset.state):enabled.add(x.dataset.state);saveFilters();render()"));

console.log('Priorities text classification: ok');
