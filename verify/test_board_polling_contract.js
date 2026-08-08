'use strict';
const assert = require('node:assert/strict');
const {createBoardPollCoordinator} = require('../bin/board-polling.js');

let active = 0, maxActive = 0, calls = 0;
const resolvers = [];
const applied = [];
const load = () => new Promise(resolve => {
  calls += 1;
  active += 1;
  maxActive = Math.max(maxActive, active);
  resolvers.push(value => { active -= 1; resolve(value); });
});
const poll = createBoardPollCoordinator(load, value => applied.push(value));

(async () => {
  const first = poll();
  poll();
  poll();
  assert.equal(calls, 1, 'overlapping requests must coalesce');
  resolvers.shift()({revision: 1});
  await first;
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(calls, 2, 'one coalesced follow-up is required');
  resolvers.shift()({revision: 2});
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(maxActive, 1, 'only one board request may be active');
  assert.deepEqual(applied.map(x => x.revision), [1, 2]);
  console.log('PASS board polling is single-flight and monotonic');
})().catch(error => { console.error(error); process.exitCode = 1; });
