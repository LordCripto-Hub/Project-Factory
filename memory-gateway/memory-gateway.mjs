#!/usr/bin/env node
import { Client } from '@modelcontextprotocol/sdk/client/index.js';
import { StreamableHTTPClientTransport } from '@modelcontextprotocol/sdk/client/streamableHttp.js';
import { fileURLToPath } from 'node:url';

const PROJECT_SLUG = /^[a-z0-9]+(?:-[a-z0-9]+)*$/;
const ENV_NAME = /^[A-Z][A-Z0-9_]{1,63}$/;
const INPUT_KEYS = new Set([
  'serverUrl',
  'projectSlug',
  'question',
  'topK',
  'hops',
  'timeoutSeconds',
  'credentialEnv',
  'maxChars',
]);
const PUBLIC_ERRORS = new Set([
  'unauthorized',
  'timeout',
  'project_mismatch',
  'invalid_response',
  'budget_exceeded',
  'unavailable',
]);

export class GatewayError extends Error {
  constructor(code) {
    super(code);
    this.name = 'GatewayError';
    this.code = code;
  }
}

function invalid(code = 'invalid_response') {
  throw new GatewayError(code);
}

export function validateInput(value, {allowHttpLoopback = false} = {}) {
  if (!value || typeof value !== 'object' || Array.isArray(value)) invalid();
  if (Object.keys(value).some(key => !INPUT_KEYS.has(key))) invalid();
  const request = {...value};
  if (typeof request.serverUrl !== 'string') invalid();
  let url;
  try {
    url = new URL(request.serverUrl);
  } catch {
    invalid();
  }
  const loopback = url.protocol === 'http:' && ['127.0.0.1', 'localhost'].includes(url.hostname);
  if (url.protocol !== 'https:' && !(allowHttpLoopback && loopback)) invalid();
  if (!PROJECT_SLUG.test(request.projectSlug || '') || request.projectSlug.length > 64) invalid();
  if (typeof request.question !== 'string') invalid();
  request.question = request.question.trim();
  if (!request.question || request.question.length > 500) invalid();
  if (!Number.isInteger(request.topK) || request.topK < 1 || request.topK > 3) invalid();
  if (request.hops !== 0) invalid();
  if (typeof request.timeoutSeconds !== 'number' || request.timeoutSeconds < 0.01 || request.timeoutSeconds > 15) invalid();
  if (!ENV_NAME.test(request.credentialEnv || '')) invalid();
  if (!Number.isInteger(request.maxChars) || request.maxChars < 256 || request.maxChars > 20000) invalid();
  request.serverUrl = url.toString();
  return request;
}

export function normalizeClaims(rawClaims, request) {
  if (!Array.isArray(rawClaims)) invalid();
  const claims = [];
  let responseChars = 0;
  let truncated = false;
  for (const raw of rawClaims) {
    if (!raw || typeof raw !== 'object' || Array.isArray(raw)) invalid();
    for (const field of ['id', 'projectSlug', 'content', 'sourceUri', 'sourceType']) {
      if (typeof raw[field] !== 'string' || !raw[field].trim()) invalid();
    }
    if (raw.projectSlug !== request.projectSlug) invalid('project_mismatch');
    if (responseChars >= request.maxChars) {
      truncated = true;
      break;
    }
    const claim = {
      id: raw.id,
      projectSlug: raw.projectSlug,
      content: raw.content,
      sourceUri: raw.sourceUri,
      sourceType: raw.sourceType,
    };
    for (const field of ['createdAt', 'updatedAt', 'status']) {
      if (raw[field] !== undefined) claim[field] = raw[field];
    }
    const remaining = request.maxChars - responseChars;
    if (claim.content.length > remaining) {
      claim.content = claim.content.slice(0, remaining);
      truncated = true;
    }
    responseChars += claim.content.length;
    claims.push(claim);
    if (truncated) break;
  }
  return {claims, truncated, responseChars, aiUsage: 'not_measured'};
}

function realClientFactory(request, token) {
  const transport = new StreamableHTTPClientTransport(new URL(request.serverUrl), {
    requestInit: {headers: {Authorization: `Bearer ${token}`}},
  });
  const client = new Client({name: 'mypeople-memory-gateway', version: '0.1.0'});
  return {
    connect: () => client.connect(transport),
    callTool: payload => client.callTool(payload),
    close: () => client.close(),
  };
}

export async function executeRecall(value, options = {}) {
  const request = validateInput(value, {allowHttpLoopback: options.allowHttpLoopback === true});
  const token = options.token || process.env[request.credentialEnv];
  if (!token) invalid('unauthorized');
  const factory = options.clientFactory || realClientFactory;
  const client = factory(request, token);
  let timer;
  try {
    await client.connect();
    const timeout = new Promise((_, reject) => {
      timer = setTimeout(() => reject(new GatewayError('timeout')), request.timeoutSeconds * 1000);
    });
    const response = await Promise.race([
      client.callTool({
        name: 'recall',
        arguments: {
          projectSlug: request.projectSlug,
          query: request.question,
          limit: request.topK,
          hops: request.hops,
        },
      }),
      timeout,
    ]);
    const claims = response?.structuredContent?.claims;
    return normalizeClaims(claims, request);
  } catch (error) {
    if (error instanceof GatewayError) throw error;
    invalid('unavailable');
  } finally {
    if (timer) clearTimeout(timer);
    try {
      await client.close();
    } catch {
      // Closing is best-effort after the typed operation result is known.
    }
  }
}

async function readStdin() {
  const chunks = [];
  for await (const chunk of process.stdin) chunks.push(chunk);
  const text = Buffer.concat(chunks).toString('utf8').trim();
  if (!text) invalid();
  try {
    return JSON.parse(text);
  } catch {
    invalid();
  }
}

export async function main() {
  const request = await readStdin();
  const result = await executeRecall(request);
  process.stdout.write(`${JSON.stringify({ok: true, ...result})}\n`);
}

if (process.argv[1] === fileURLToPath(import.meta.url)) {
  main().catch(error => {
    const code = PUBLIC_ERRORS.has(error?.code) ? error.code : 'unavailable';
    process.stdout.write(`${JSON.stringify({ok: false, error: code})}\n`);
    process.exitCode = 1;
  });
}
