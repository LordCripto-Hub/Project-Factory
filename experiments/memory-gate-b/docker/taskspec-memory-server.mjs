#!/usr/bin/env node
import {spawn} from 'node:child_process';
import {createHash} from 'node:crypto';
import {appendFileSync, readFileSync, writeFileSync} from 'node:fs';
import {createServer as createHttpServer} from 'node:http';
import {createServer as createHttpsServer} from 'node:https';

import {McpServer} from '@modelcontextprotocol/sdk/server/mcp.js';
import {StreamableHTTPServerTransport} from '@modelcontextprotocol/sdk/server/streamableHttp.js';
import {createMcpExpressApp} from '@modelcontextprotocol/sdk/server/express.js';
import * as z from 'zod/v4';


const host = process.env.MYPEOPLE_GATE_B_HOST || '127.0.0.1';
const port = Number(process.env.MYPEOPLE_GATE_B_PORT || '18443');
const liveCanary = process.env.MYPEOPLE_GATE_B_LIVE_CANARY === '1';
const tokenPath = process.env.MYPEOPLE_GATE_B_TOKEN_FILE;
const token = (process.env.MYPEOPLE_MEMORY_TOKEN || (tokenPath ? readFileSync(tokenPath, 'utf8') : '')).trim();
const ledgerPath = process.env.MYPEOPLE_GATE_B_LEDGER;
const readyPath = process.env.MYPEOPLE_GATE_B_READY;

if (
  !token || !ledgerPath || !readyPath || !Number.isInteger(port) ||
  (!liveCanary && host !== '127.0.0.1') ||
  (liveCanary && host !== '0.0.0.0')
) {
  throw new Error('gate_b_configuration_invalid');
}

function runRecall(argumentsValue) {
  return new Promise((resolve, reject) => {
    const child = spawn(
      'python3',
      [
        '/workspace/scripts/query_taskspec_memory.py',
        '--dataset',
        '/project-factory-history-80dce6f86632',
        '--lock',
        '/workspace/docker/history-hybrid.dataset-lock.json',
      ],
      {
        env: {
          PATH: process.env.PATH,
          HOME: process.env.HOME,
          LANG: process.env.LANG || 'C.UTF-8',
          PYTHONPATH: '/workspace/src',
          PYTHONDONTWRITEBYTECODE: '1',
        },
        shell: false,
        stdio: ['pipe', 'pipe', 'pipe'],
      },
    );
    const stdout = [];
    child.stdout.on('data', chunk => stdout.push(chunk));
    child.on('error', reject);
    child.on('close', code => {
      if (code !== 0) {
        reject(new Error('recall_bridge_failed'));
        return;
      }
      try {
        resolve(JSON.parse(Buffer.concat(stdout).toString('utf8')));
      } catch {
        reject(new Error('recall_bridge_invalid'));
      }
    });
    child.stdin.end(JSON.stringify(argumentsValue));
  });
}

const app = createMcpExpressApp({
  host,
  allowedHosts: liveCanary ? ['memory-gate-b'] : ['127.0.0.1', 'localhost'],
});
app.use((request, response, next) => {
  if (request.headers.authorization !== `Bearer ${token}`) {
    response.status(401).json({error: 'unauthorized'});
    return;
  }
  next();
});

app.post('/mcp', async (request, response) => {
  const mcp = new McpServer({name: 'gate-b-history-memory', version: '1.0.0'});
  mcp.registerTool('recall', {
    inputSchema: {
      projectSlug: z.literal('project-factory'),
      query: z.string().min(1).max(500),
      limit: z.number().int().min(1).max(3),
      hops: z.literal(0),
    },
  }, async argumentsValue => {
    const result = await runRecall(argumentsValue);
    appendFileSync(
      ledgerPath,
      JSON.stringify({
        requestIndex: readFileSync(ledgerPath, 'utf8').split('\n').filter(Boolean).length + 1,
        projectSlug: argumentsValue.projectSlug,
        queryDigest: createHash('sha256').update(argumentsValue.query).digest('hex'),
        topK: argumentsValue.limit,
        hops: argumentsValue.hops,
        claimCount: result.claims.length,
      }) + '\n',
      {encoding: 'utf8', mode: 0o600},
    );
    return {
      content: [{type: 'text', text: 'recall complete'}],
      structuredContent: {
        claims: result.claims,
        aiUsage: result.aiUsage,
      },
    };
  });
  const transport = new StreamableHTTPServerTransport({
    sessionIdGenerator: undefined,
  });
  response.on('close', () => {
    transport.close().catch(() => {});
    mcp.close().catch(() => {});
  });
  await mcp.connect(transport);
  await transport.handleRequest(request, response, request.body);
});

writeFileSync(ledgerPath, '', {encoding: 'utf8', mode: 0o600});
let server;
if (liveCanary) {
  if (process.env.MYPEOPLE_GATE_B_TLS_KEY || process.env.MYPEOPLE_GATE_B_TLS_CERT) {
    throw new Error('gate_b_configuration_invalid');
  }
  server = createHttpServer(app);
} else {
  const key = readFileSync(process.env.MYPEOPLE_GATE_B_TLS_KEY);
  const cert = readFileSync(process.env.MYPEOPLE_GATE_B_TLS_CERT);
  server = createHttpsServer({key, cert}, app);
}
server.listen(port, host, () => {
  writeFileSync(
    readyPath,
    JSON.stringify({url: `${liveCanary ? 'http' : 'https'}://${host}:${port}/mcp`}) + '\n',
    {encoding: 'utf8', mode: 0o600},
  );
});

process.on('SIGTERM', () => server.close(() => process.exit(0)));
