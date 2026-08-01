#!/usr/bin/env node
import {spawn} from 'node:child_process';
import {createHash} from 'node:crypto';
import {appendFileSync, readFileSync, writeFileSync} from 'node:fs';
import {createServer} from 'node:http';

import {McpServer} from '@modelcontextprotocol/sdk/server/mcp.js';
import {StreamableHTTPServerTransport} from '@modelcontextprotocol/sdk/server/streamableHttp.js';
import {createMcpExpressApp} from '@modelcontextprotocol/sdk/server/express.js';
import * as z from 'zod/v4';


const host = '127.0.0.1';
const port = 18443;
const required = name => {
  const value = process.env[name];
  if (!value) throw new Error('local_memory_configuration_invalid');
  return value;
};
const token = readFileSync(required('MYPEOPLE_LOCAL_MEMORY_TOKEN_FILE'), 'utf8').trim();
const ledgerPath = required('MYPEOPLE_LOCAL_MEMORY_LEDGER');
const readyPath = required('MYPEOPLE_LOCAL_MEMORY_READY');
const queryPath = required('MYPEOPLE_LOCAL_MEMORY_QUERY');
const datasetPath = required('MYPEOPLE_LOCAL_MEMORY_DATASET');
const lockPath = required('MYPEOPLE_LOCAL_MEMORY_LOCK');
const runtimePath = required('MYPEOPLE_LOCAL_MEMORY_RUNTIME');
if (!token) throw new Error('local_memory_configuration_invalid');

function runRecall(argumentsValue) {
  return new Promise((resolve, reject) => {
    const child = spawn('python3', [
      queryPath, '--dataset', datasetPath, '--lock', lockPath, '--runtime', runtimePath,
    ], {
      env: {
        PATH: process.env.PATH,
        HOME: process.env.HOME,
        LANG: process.env.LANG || 'C.UTF-8',
        PYTHONPATH: `${process.env.INSTALL_DIR}/experiments/memory-gate-b/src:${process.env.INSTALL_DIR}/bin`,
        PYTHONDONTWRITEBYTECODE: '1',
      },
      shell: false,
      stdio: ['pipe', 'pipe', 'pipe'],
    });
    const stdout = [];
    child.stdout.on('data', chunk => stdout.push(chunk));
    child.on('error', reject);
    child.on('close', code => {
      if (code !== 0) return reject(new Error('recall_bridge_failed'));
      try { resolve(JSON.parse(Buffer.concat(stdout).toString('utf8'))); }
      catch { reject(new Error('recall_bridge_invalid')); }
    });
    child.stdin.end(JSON.stringify(argumentsValue));
  });
}

const app = createMcpExpressApp({host, allowedHosts: [host, 'localhost']});
app.use((request, response, next) => {
  if (request.headers.authorization !== `Bearer ${token}`) {
    response.status(401).json({error: 'unauthorized'});
    return;
  }
  next();
});
app.post('/mcp', async (request, response) => {
  const mcp = new McpServer({name: 'mypeople-local-hybrid-memory', version: '1.0.0'});
  mcp.registerTool('recall', {inputSchema: {
    projectSlug: z.literal('project-factory'),
    query: z.string().min(1).max(800),
    limit: z.number().int().min(1).max(3),
    hops: z.literal(0),
  }}, async argumentsValue => {
    const result = await runRecall(argumentsValue);
    appendFileSync(ledgerPath, JSON.stringify({
      queryDigest: createHash('sha256').update(argumentsValue.query).digest('hex'),
      topK: argumentsValue.limit,
      claimCount: result.claims.length,
      status: result.status,
      selectedLevel: result.selectedLevel,
      levelsAttempted: result.levelsAttempted,
      elapsedMilliseconds: result.elapsedMilliseconds,
      examinedCount: result.examinedCount,
      estimatedTokens: result.estimatedTokens,
      provenanceComplete: result.provenanceComplete,
      reasonCode: result.reasonCode,
    }) + '\n', {encoding: 'utf8', mode: 0o600});
    return {content: [{type: 'text', text: 'recall complete'}], structuredContent: {...result}};
  });
  const transport = new StreamableHTTPServerTransport({sessionIdGenerator: undefined});
  response.on('close', () => {
    transport.close().catch(() => {});
    mcp.close().catch(() => {});
  });
  await mcp.connect(transport);
  await transport.handleRequest(request, response, request.body);
});

writeFileSync(ledgerPath, '', {encoding: 'utf8', mode: 0o600});
const server = createServer(app);
server.listen(port, host, () => {
  writeFileSync(readyPath, JSON.stringify({schema: 1, ready: true}) + '\n', {encoding: 'utf8', mode: 0o600});
});
process.on('SIGTERM', () => server.close(() => process.exit(0)));
