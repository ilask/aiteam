#!/usr/bin/env node
import { CentralHub } from './index.js';
import { CodexAdapter } from './adapters/codex.js';
import { ClaudeAdapter } from './adapters/claude.js';
import { GeminiAdapter } from './adapters/gemini.js';
import { WebSocket } from 'ws';
import * as readline from 'readline';
import * as net from 'net';
import { fileURLToPath } from 'url';
import * as path from 'path';
import * as fs from 'fs';

const DEFAULT_PORT = process.env.PORT ? parseInt(process.env.PORT, 10) : 4501;
const SUPPORTED_AGENTS = ['codex', 'claude', 'gemini'] as const;
type SupportedAgentId = (typeof SUPPORTED_AGENTS)[number];
const DEFAULT_MAIN_AGENT: SupportedAgentId = 'codex';
const CLI_MESSAGE_DEDUP_WINDOW_MS = 600;
const parsedSysProgressInterval = process.env.AITEAM_SYS_PROGRESS_INTERVAL_MS
  ? parseInt(process.env.AITEAM_SYS_PROGRESS_INTERVAL_MS, 10)
  : Number.NaN;
const SYS_PROGRESS_MIN_INTERVAL_MS =
  Number.isFinite(parsedSysProgressInterval) && parsedSysProgressInterval > 0
    ? Math.max(1000, parsedSysProgressInterval)
    : 5000;
const IGNORED_RPC_METHODS = new Set([
  'thread/started',
  'thread/updated',
  'turn/started',
  'token_count'
]);

type JsonRecord = Record<string, unknown>;

function asRecord(value: unknown): JsonRecord | null {
  if (value && typeof value === 'object' && !Array.isArray(value)) {
    return value as JsonRecord;
  }
  return null;
}

function normalizeText(text: string): string | null {
  return text.trim().length > 0 ? text : null;
}

function normalizeType(value: unknown): string | null {
  if (typeof value !== 'string') {
    return null;
  }
  return value.replace(/[^a-z]/gi, '').toLowerCase();
}

function extractTextFromContent(content: unknown): string {
  if (typeof content === 'string') {
    return content;
  }

  if (!Array.isArray(content)) {
    return '';
  }

  return content
    .map((part) => {
      if (typeof part === 'string') {
        return part;
      }
      const partRecord = asRecord(part);
      if (!partRecord) {
        return '';
      }
      if (typeof partRecord.text === 'string') {
        return partRecord.text;
      }
      if (typeof partRecord.output_text === 'string') {
        return partRecord.output_text;
      }
      return '';
    })
    .join('');
}

function extractTextFromItem(item: unknown): string {
  const itemRecord = asRecord(item);
  if (!itemRecord) {
    return '';
  }

  const role =
    typeof itemRecord.role === 'string' ? itemRecord.role.toLowerCase() : null;
  const itemType = normalizeType(itemRecord.type);
  const isAssistantMessage =
    role === 'assistant' || itemType === 'agentmessage';

  if (!isAssistantMessage) {
    return '';
  }

  const contentText = extractTextFromContent(itemRecord.content);
  if (contentText) {
    return contentText;
  }
  if (typeof itemRecord.text === 'string') {
    return itemRecord.text;
  }
  if (typeof itemRecord.message === 'string') {
    return itemRecord.message;
  }
  if (typeof itemRecord.output_text === 'string') {
    return itemRecord.output_text;
  }
  return '';
}

function extractTextFromTurn(turn: unknown): string {
  const turnRecord = asRecord(turn);
  if (!turnRecord) {
    return '';
  }

  const outputTexts: string[] = [];
  if (Array.isArray(turnRecord.output)) {
    outputTexts.push(...turnRecord.output.map((outputItem) => extractTextFromItem(outputItem)));
  }
  if (Array.isArray(turnRecord.items)) {
    outputTexts.push(...turnRecord.items.map((turnItem) => extractTextFromItem(turnItem)));
  }

  return outputTexts.join('');
}

function extractTextFromEvent(event: unknown): string {
  const eventRecord = asRecord(event);
  if (!eventRecord) {
    return '';
  }

  if (typeof eventRecord.text === 'string') {
    return eventRecord.text;
  }
  if (typeof eventRecord.message === 'string') {
    return eventRecord.message;
  }
  if (typeof eventRecord.output_text === 'string') {
    return eventRecord.output_text;
  }
  if (typeof eventRecord.last_agent_message === 'string') {
    return eventRecord.last_agent_message;
  }

  const itemRecord = asRecord(eventRecord.item);
  if (itemRecord) {
    return extractTextFromItem(itemRecord);
  }

  return extractTextFromContent(eventRecord.content);
}

function extractTextFromCodexEvent(payloadRecord: JsonRecord): string {
  const method =
    typeof payloadRecord.method === 'string' ? payloadRecord.method : null;
  if (!method || !method.startsWith('codex/event/')) {
    return '';
  }

  const paramsRecord = asRecord(payloadRecord.params);
  if (!paramsRecord) {
    return '';
  }

  const msgRecord =
    asRecord(paramsRecord.msg) ??
    asRecord(paramsRecord.event) ??
    asRecord(paramsRecord.message);
  if (!msgRecord) {
    return '';
  }

  const eventType = typeof msgRecord.type === 'string' ? msgRecord.type : null;
  if (method === 'codex/event/agent_message' || eventType === 'agent_message') {
    if (typeof msgRecord.message === 'string') {
      return msgRecord.message;
    }
    return extractTextFromItem(msgRecord.item);
  }

  if (method === 'codex/event/item_completed' || eventType === 'item_completed') {
    return extractTextFromItem(msgRecord.item);
  }

  if (
    method === 'codex/event/task_complete' ||
    eventType === 'task_complete' ||
    eventType === 'turn_complete'
  ) {
    if (typeof msgRecord.last_agent_message === 'string') {
      return msgRecord.last_agent_message;
    }
  }

  return '';
}

export function extractConversationalText(payload: unknown): string | null {
  if (typeof payload === 'string') {
    return normalizeText(payload);
  }

  const payloadRecord = asRecord(payload);
  if (!payloadRecord) {
    return null;
  }

  if (
    typeof payloadRecord.method === 'string' &&
    IGNORED_RPC_METHODS.has(payloadRecord.method)
  ) {
    return null;
  }

  if (typeof payloadRecord.error === 'string') {
    const details: string[] = [];
    if (typeof payloadRecord.target === 'string') {
      details.push(`target=${payloadRecord.target}`);
    }
    if (typeof payloadRecord.reason === 'string') {
      details.push(payloadRecord.reason);
    }
    if (typeof payloadRecord.exitCode === 'number') {
      details.push(`exit=${payloadRecord.exitCode}`);
    }
    if (payloadRecord.timedOut === true) {
      details.push('timedOut');
    }

    const suffix = details.length > 0 ? ` (${details.join(', ')})` : '';
    return normalizeText(`${payloadRecord.error}${suffix}`);
  }

  const codexEventText = extractTextFromCodexEvent(payloadRecord);
  if (normalizeText(codexEventText)) {
    return codexEventText;
  }

  if (typeof payloadRecord.message === 'string') {
    return normalizeText(payloadRecord.message);
  }

  const messageRecord = asRecord(payloadRecord.message);
  if (messageRecord) {
    const messageText = extractTextFromContent(messageRecord.content);
    if (normalizeText(messageText)) {
      return messageText;
    }
    if (typeof messageRecord.message === 'string') {
      return normalizeText(messageRecord.message);
    }
  }

  if (typeof payloadRecord.result === 'string') {
    return normalizeText(payloadRecord.result);
  }

  const resultRecord = asRecord(payloadRecord.result);
  if (resultRecord) {
    if (typeof resultRecord.output_text === 'string') {
      const outputText = normalizeText(resultRecord.output_text);
      if (outputText) {
        return outputText;
      }
    }

    const turnText = extractTextFromTurn(resultRecord.turn);
    if (normalizeText(turnText)) {
      return turnText;
    }

    const resultContentText = extractTextFromContent(resultRecord.content);
    if (normalizeText(resultContentText)) {
      return resultContentText;
    }
  }

  const paramsRecord = asRecord(payloadRecord.params);
  if (paramsRecord) {
    const itemText = extractTextFromItem(paramsRecord.item);
    if (normalizeText(itemText)) {
      return itemText;
    }

    const turnText = extractTextFromTurn(paramsRecord.turn);
    if (normalizeText(turnText)) {
      return turnText;
    }

    const eventText = extractTextFromEvent(paramsRecord.event);
    if (normalizeText(eventText)) {
      return eventText;
    }
  }

  if (typeof payloadRecord.text === 'string') {
    return normalizeText(payloadRecord.text);
  }
  if (typeof payloadRecord.output_text === 'string') {
    return normalizeText(payloadRecord.output_text);
  }

  const contentText = extractTextFromContent(payloadRecord.content);
  return normalizeText(contentText);
}

export function formatCliMessage(message: unknown): { from: string; text: string } | null {
  const messageRecord = asRecord(message);
  if (!messageRecord) {
    return null;
  }

  if (typeof messageRecord.error === 'string') {
    const details: string[] = [];
    if (typeof messageRecord.target === 'string') {
      details.push(`target=${messageRecord.target}`);
    }
    if (typeof messageRecord.reason === 'string') {
      details.push(messageRecord.reason);
    }
    const suffix = details.length > 0 ? ` (${details.join(', ')})` : '';
    return {
      from: 'hub',
      text: `${messageRecord.error}${suffix}`
    };
  }

  if (typeof messageRecord.from !== 'string') {
    return null;
  }

  const text = extractConversationalText(messageRecord.payload);
  if (!text) {
    return null;
  }

  return {
    from: messageRecord.from,
    text
  };
}

function isSupportedAgentId(value: string): value is SupportedAgentId {
  return SUPPORTED_AGENTS.includes(value as SupportedAgentId);
}

function printAiOrientedHelp() {
  console.log('aiteam - Agent Team CLI');
  console.log('');
  console.log('Usage:');
  console.log('  aiteam [main-agent]');
  console.log('  aiteam -h | --help');
  console.log('');
  console.log(`Main agent choices: ${SUPPORTED_AGENTS.join(', ')} (default: ${DEFAULT_MAIN_AGENT})`);
  console.log('');
  console.log('Runtime model:');
  console.log('- visible role: lead (single user-facing prompt)');
  console.log('- main role: selected main agent receives plain-text user input');
  console.log('- peer roles: other agents run headless and communicate via hub routing');
  console.log('');
  console.log('Input model:');
  console.log('- plain text: sent to main agent');
  console.log('- @<agent> <task>: direct route to specific agent');
  console.log('- /status: print self/main/peer connectivity and routed counters');
  console.log('- exit | quit: shutdown');
  console.log('');
  console.log('Inter-agent contract:');
  console.log('- agents delegate with a single line: @<agent> <task>');
  console.log('- supported agent ids: codex, claude, gemini');
  console.log('- autonomy policy: prefer agent-to-agent collaboration before lead reporting');
}

function parseCliArgs(argv: string[]): { showHelp: boolean; mainAgent: SupportedAgentId } {
  let showHelp = false;
  let mainAgent: SupportedAgentId = DEFAULT_MAIN_AGENT;
  let hasMainAgentOverride = false;

  for (const rawArg of argv) {
    const arg = rawArg.trim();
    if (!arg) {
      continue;
    }

    if (arg === '-h' || arg === '--help') {
      showHelp = true;
      continue;
    }

    if (arg.startsWith('-')) {
      throw new Error(`Unknown option: ${arg}`);
    }

    if (hasMainAgentOverride) {
      throw new Error(`Unexpected positional argument: ${arg}`);
    }

    if (!isSupportedAgentId(arg)) {
      throw new Error(
        `Unsupported main agent "${arg}". Supported: ${SUPPORTED_AGENTS.join(', ')}.`
      );
    }

    hasMainAgentOverride = true;
    mainAgent = arg;
  }

  return { showHelp, mainAgent };
}

async function canListenOnPort(port: number): Promise<boolean> {
  return new Promise<boolean>((resolve) => {
    const server = net.createServer();
    server.once('error', () => {
      resolve(false);
    });
    server.once('listening', () => {
      server.close(() => resolve(true));
    });
    server.listen(port);
  });
}

async function allocateFreePort(): Promise<number> {
  return new Promise<number>((resolve, reject) => {
    const server = net.createServer();
    server.once('error', reject);
    server.once('listening', () => {
      const address = server.address();
      if (!address || typeof address === 'string') {
        server.close(() => reject(new Error('Failed to allocate a free port.')));
        return;
      }
      const selectedPort = address.port;
      server.close((closeError) => {
        if (closeError) {
          reject(closeError);
          return;
        }
        resolve(selectedPort);
      });
    });
    server.listen(0);
  });
}

async function resolveHubPort(preferredPort: number): Promise<number> {
  if (await canListenOnPort(preferredPort)) {
    return preferredPort;
  }
  const fallbackPort = await allocateFreePort();
  console.log(`[aiteam] Port ${preferredPort} is in use. Using port ${fallbackPort}.`);
  return fallbackPort;
}

function formatHubStatus(hub: CentralHub, mainAgent: SupportedAgentId): string {
  const snapshot = hub.getStatusSnapshot();
  const connectedSet = new Set(snapshot.connectedAgents);
  const pairSummary =
    snapshot.routePairs.length > 0
      ? snapshot.routePairs.map((pair) => `${pair.from}->${pair.to}=${pair.count}`).join(', ')
      : '(none)';
  const delegateCount =
    snapshot.routeEvents.find((eventEntry) => eventEntry.eventType === 'delegate')?.count ?? 0;
  const promptCount =
    snapshot.routeEvents.find((eventEntry) => eventEntry.eventType === 'prompt')?.count ?? 0;

  const lines = [
    '[status]',
    '- self(lead): connected',
    `- main: ${mainAgent}`,
    `- codex: ${connectedSet.has('codex') ? 'connected' : 'disconnected'}`,
    `- claude: ${connectedSet.has('claude') ? 'connected' : 'disconnected'}`,
    `- gemini: ${connectedSet.has('gemini') ? 'connected' : 'disconnected'}`,
    `- routed.pairs: ${pairSummary}`,
    `- routed.prompt: ${promptCount}`,
    `- routed.delegate: ${delegateCount}`,
    '- communication: user plain text routes to main; AI delegates via "@<agent> <task>"',
    '- note: routed.delegate counts AI-origin delegate events only'
  ];
  return lines.join('\n');
}

async function main() {
  let cliArgs: { showHelp: boolean; mainAgent: SupportedAgentId };
  try {
    cliArgs = parseCliArgs(process.argv.slice(2));
  } catch (error) {
    console.error(String((error as Error).message ?? error));
    console.error('Use "aiteam -h" for usage.');
    process.exit(1);
    return;
  }

  if (cliArgs.showHelp) {
    printAiOrientedHelp();
    return;
  }

  const mainAgent = cliArgs.mainAgent;
  const hubPort = await resolveHubPort(DEFAULT_PORT);
  console.log('Starting aiteam v2 (Headless Architecture)...');
  
  let hub: CentralHub;
  try {
    hub = new CentralHub(hubPort);
  } catch (err) {
    console.error('Failed to start Hub server:', err);
    process.exit(1);
    return;
  }
  
  const hubUrl = `ws://localhost:${hubPort}`;
  const codex = new CodexAdapter(hubUrl, 'codex');
  const claude = new ClaudeAdapter(hubUrl, 'claude');
  const gemini = new GeminiAdapter(hubUrl, 'gemini');

  await Promise.all([
    codex.start().catch(e => console.error('Codex failed to start', e)),
    claude.start().catch(e => console.error('Claude failed to start', e)),
    gemini.start().catch(e => console.error('Gemini failed to start', e))
  ]);

  const ws = new WebSocket(hubUrl);
  
  const rl = readline.createInterface({
    input: process.stdin,
    output: process.stdout,
    historySize: 1000
  });

  let isShuttingDown = false;
  let hiddenMessageCount = 0;
  let lastRenderedHiddenMessageCount = 0;
  let lastSystemProgressAt = 0;
  let waitingForResponse = false;
  let waitingTarget: string | null = null;
  let waitingStartedAt = 0;
  const recentCliMessages = new Map<string, number>();
  let systemProgressTimer: NodeJS.Timeout | null = null;

  function showPrompt() {
    if (isShuttingDown) return;
    rl.setPrompt(`You(${mainAgent})> `);
    rl.prompt();
  }

  function renderSystemProgress(force = false) {
    if (isShuttingDown || !waitingForResponse) {
      return;
    }

    if (!force && hiddenMessageCount === 0 && lastRenderedHiddenMessageCount === 0) {
      return;
    }

    const now = Date.now();
    if (!force && now - lastSystemProgressAt < SYS_PROGRESS_MIN_INTERVAL_MS) {
      return;
    }
    if (
      !force &&
      hiddenMessageCount === lastRenderedHiddenMessageCount &&
      hiddenMessageCount > 0
    ) {
      return;
    }

    lastSystemProgressAt = now;
    lastRenderedHiddenMessageCount = hiddenMessageCount;
    const waitingOn = waitingTarget ?? mainAgent;
    const elapsedMs = waitingStartedAt > 0 ? now - waitingStartedAt : 0;
    const elapsedSeconds = Math.max(0, Math.floor(elapsedMs / 1000));
    readline.clearLine(process.stdout, 0);
    readline.cursorTo(process.stdout, 0);
    if (hiddenMessageCount > 0) {
      console.log(`\n[sys:${hiddenMessageCount}] waiting for ${waitingOn}... (${elapsedSeconds}s)`);
    } else {
      console.log(`\n[sys] waiting for ${waitingOn}... (${elapsedSeconds}s)`);
    }
    showPrompt();
  }

  function beginWaitingForResponse(target: string) {
    waitingForResponse = true;
    waitingTarget = target;
    waitingStartedAt = Date.now();
    hiddenMessageCount = 0;
    lastRenderedHiddenMessageCount = 0;
    lastSystemProgressAt = 0;
    renderSystemProgress(true);
  }

  function endWaitingForResponse() {
    waitingForResponse = false;
    waitingTarget = null;
    waitingStartedAt = 0;
    hiddenMessageCount = 0;
    lastRenderedHiddenMessageCount = 0;
    lastSystemProgressAt = 0;
  }

  ws.on('open', () => {
    ws.send(JSON.stringify({ type: 'identify', id: 'lead' }));
    console.log('\n--- aiteam CLI ---');
    console.log(`Main agent: ${mainAgent} (default: ${DEFAULT_MAIN_AGENT})`);
    console.log(`Available agents: ${SUPPORTED_AGENTS.join(', ')}`);
    console.log(`Type plain text to send tasks to ${mainAgent}.`);
    console.log('Type "@agent message" for explicit routing.');
    console.log('Type "/status" to inspect self/peer connection states.');
    systemProgressTimer = setInterval(() => {
      renderSystemProgress(false);
    }, SYS_PROGRESS_MIN_INTERVAL_MS);
    showPrompt();
  });

  ws.on('error', (err) => {
    if (!isShuttingDown) console.error('\n[Lead WS Error]', err);
  });

  ws.on('close', () => {
    if (!isShuttingDown) {
        console.log('\n[Lead WS Closed] Connection to Hub lost.');
        cleanup();
    }
  });

  ws.on('message', (data) => {
    let displayMessage: { from: string; text: string } | null = null;
    let sender: string | null = null;
    try {
      const parsed = JSON.parse(data.toString());
      if (parsed && typeof parsed === 'object' && !Array.isArray(parsed)) {
        sender = typeof (parsed as Record<string, unknown>).from === 'string'
          ? ((parsed as Record<string, unknown>).from as string)
          : null;
      }
      displayMessage = formatCliMessage(parsed);
      if (
        !displayMessage &&
        waitingForResponse &&
        (!waitingTarget || sender === waitingTarget)
      ) {
        hiddenMessageCount += 1;
        renderSystemProgress(false);
      }
    } catch {
      return;
    }

    if (!displayMessage) {
      return;
    }

    if (
      waitingForResponse &&
      (displayMessage.from === 'hub' || !waitingTarget || displayMessage.from === waitingTarget)
    ) {
      endWaitingForResponse();
    }

    const now = Date.now();
    for (const [messageKey, timestamp] of recentCliMessages.entries()) {
      if (now - timestamp > CLI_MESSAGE_DEDUP_WINDOW_MS) {
        recentCliMessages.delete(messageKey);
      }
    }
    const dedupKey = `${displayMessage.from}\u0000${displayMessage.text}`;
    const previous = recentCliMessages.get(dedupKey);
    if (previous !== undefined && now - previous <= CLI_MESSAGE_DEDUP_WINDOW_MS) {
      return;
    }
    recentCliMessages.set(dedupKey, now);

    readline.clearLine(process.stdout, 0);
    readline.cursorTo(process.stdout, 0);
    console.log(`\n[${displayMessage.from}] ${displayMessage.text}`);
    showPrompt();
  });

  rl.on('line', (line) => {
    if (isShuttingDown) {
      return;
    }

    const rawLine = line ?? '';
    const trimmedLine = rawLine.trim();

    if (trimmedLine.length === 0) {
      showPrompt();
      return;
    }

    if (trimmedLine === 'exit' || trimmedLine === 'quit') {
      cleanup();
      return;
    }

    if (trimmedLine === '/status') {
      readline.clearLine(process.stdout, 0);
      readline.cursorTo(process.stdout, 0);
      console.log(`\n${formatHubStatus(hub, mainAgent)}`);
      showPrompt();
      return;
    }

    if (waitingForResponse) {
      const waitingOn = waitingTarget ?? mainAgent;
      console.log(`[aiteam] Still waiting for ${waitingOn}. Please wait or use /status.`);
      showPrompt();
      return;
    }

    let target: string = mainAgent;
    let payload = rawLine;
    const explicitRoute = rawLine.match(/^@(\w+)\s+([\s\S]*)$/);
    if (explicitRoute) {
      target = explicitRoute[1];
      payload = explicitRoute[2];
      if (payload.trim().length === 0) {
        console.log('Invalid format. Use "@agent message".');
        showPrompt();
        return;
      }
    } else if (trimmedLine.startsWith('@')) {
      console.log('Invalid format. Use "@agent message".');
      showPrompt();
      return;
    }

    if (ws.readyState !== WebSocket.OPEN) {
      console.log('[aiteam] Hub connection is not ready.');
      showPrompt();
      return;
    }

    ws.send(
      JSON.stringify({
        from: 'lead',
        to: target,
        eventType: 'prompt',
        payload
      })
    );
    beginWaitingForResponse(target);
    showPrompt();
  });

  function cleanup() {
    if (isShuttingDown) return;
    isShuttingDown = true;
    console.log('\nShutting down...');
    if (systemProgressTimer) {
      clearInterval(systemProgressTimer);
      systemProgressTimer = null;
    }
    rl.close();
    ws.close();
    codex.stop();
    claude.stop();
    gemini.stop();
    hub.stop();
    setTimeout(() => process.exit(0), 100);
  }

  rl.on('close', cleanup);
  process.on('SIGINT', cleanup);
  process.on('SIGTERM', cleanup);
}

function isExecutedAsEntryPoint(): boolean {
  const entryScript = process.argv[1];
  if (!entryScript) {
    return false;
  }

  const normalizeForCompare = (pathLike: string): string => {
    const resolved = path.resolve(pathLike);
    const realPath = fs.existsSync(resolved) ? fs.realpathSync.native(resolved) : resolved;
    return realPath.replace(/\\/g, '/').toLowerCase();
  };

  try {
    const entryPath = normalizeForCompare(entryScript);
    const modulePath = normalizeForCompare(fileURLToPath(import.meta.url));
    return entryPath === modulePath;
  } catch {
    return false;
  }
}

if (isExecutedAsEntryPoint()) {
  main().catch((error) => {
    console.error(error);
    process.exit(1);
  });
}
