import assert from 'node:assert/strict';
import test from 'node:test';

import { McpServer } from '@modelcontextprotocol/sdk/server/mcp.js';
import { StreamableHTTPServerTransport } from '@modelcontextprotocol/sdk/server/streamableHttp.js';
import { createMcpExpressApp } from '@modelcontextprotocol/sdk/server/express.js';
import * as z from 'zod/v4';

import { executeRecall, normalizeClaims, validateInput } from '../memory-gateway.mjs';

const input = {
  serverUrl: 'https://memory.example.invalid/mcp',
  projectSlug: 'mypeople',
  question: 'Which constraint applies?',
  topK: 3,
  hops: 0,
  timeoutSeconds: 8,
  credentialEnv: 'MYPEOPLE_MEMORY_TOKEN',
  maxChars: 2000,
};

const claim = {
  id: 'fixture-1',
  projectSlug: 'mypeople',
  content: 'Synthetic verified constraint.',
  sourceUri: 'task://fixture-1',
  sourceType: 'verified-task',
  createdAt: 1,
  updatedAt: 1,
  status: 'canonical',
};

test('accepts only the bounded recall contract', () => {
  assert.equal(validateInput(input).projectSlug, 'mypeople');
  for (const bad of [
    {...input, topK: 4},
    {...input, hops: 1},
    {...input, tool: 'remember'},
    {...input, serverUrl: 'http://remote.example/mcp'},
    {...input, question: 'x'.repeat(501)},
    {...input, maxChars: 20100},
  ]) assert.throws(() => validateInput(bad));
});

test('rejects missing provenance and cross-project claims', () => {
  assert.throws(() => normalizeClaims([{id: '1', projectSlug: 'mypeople', content: 'x'}], input));
  assert.throws(() => normalizeClaims([{...claim, projectSlug: 'other'}], input));
});

test('calls only recall and closes the client', async () => {
  const calls = [];
  const fake = {
    connect: async () => calls.push('connect'),
    callTool: async request => {
      calls.push(request.name);
      return {structuredContent: {claims: [claim]}};
    },
    close: async () => calls.push('close'),
  };
  const result = await executeRecall(input, {token: 'test-token', clientFactory: () => fake});
  assert.deepEqual(calls, ['connect', 'recall', 'close']);
  assert.equal(result.claims.length, 1);
});

test('closes the client after timeout', async () => {
  let closed = false;
  const fake = {
    connect: async () => {},
    callTool: async () => new Promise(() => {}),
    close: async () => { closed = true; },
  };
  await assert.rejects(
    executeRecall({...input, timeoutSeconds: 0.02}, {token: 'x', clientFactory: () => fake}),
    /timeout/
  );
  assert.equal(closed, true);
});

test('uses the official Streamable HTTP client against a local recall-only server', async () => {
  const app = createMcpExpressApp();
  let received;
  app.post('/mcp', async (req, res) => {
    const server = new McpServer({name: 'fixture-memory', version: '0.1.0'});
    server.registerTool('recall', {
      inputSchema: {
        projectSlug: z.string(),
        query: z.string(),
        limit: z.number().int(),
        hops: z.number().int(),
      },
    }, async args => {
      received = args;
      return {
        content: [{type: 'text', text: 'synthetic'}],
        structuredContent: {claims: [claim]},
      };
    });
    const transport = new StreamableHTTPServerTransport({sessionIdGenerator: undefined});
    res.on('close', () => {
      transport.close().catch(() => {});
      server.close().catch(() => {});
    });
    await server.connect(transport);
    await transport.handleRequest(req, res, req.body);
  });
  const listener = await new Promise(resolve => {
    const instance = app.listen(0, '127.0.0.1', () => resolve(instance));
  });
  try {
    const address = listener.address();
    const result = await executeRecall(
      {...input, serverUrl: `http://127.0.0.1:${address.port}/mcp`},
      {token: 'fixture-token', allowHttpLoopback: true}
    );
    assert.deepEqual(received, {
      projectSlug: 'mypeople',
      query: input.question,
      limit: 3,
      hops: 0,
    });
    assert.equal(result.claims[0].sourceUri, 'task://fixture-1');
  } finally {
    await new Promise(resolve => listener.close(resolve));
  }
});
