#!/usr/bin/env node
import { CentralHub } from './index.js';
import { CodexAdapter } from './adapters/codex.js';
import { ClaudeAdapter } from './adapters/claude.js';
import { GeminiAdapter } from './adapters/gemini.js';
import { WebSocket } from 'ws';
import * as readline from 'readline';
import { fileURLToPath } from 'url';
import * as path from 'path';

const PORT = process.env.PORT ? parseInt(process.env.PORT, 10) : 4501;
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

function extractTextFromTurn(turn: unknown): string {
  const turnRecord = asRecord(turn);
  if (!turnRecord || !Array.isArray(turnRecord.output)) {
    return '';
  }

  return turnRecord.output
    .map((outputItem) => {
      const itemRecord = asRecord(outputItem);
      if (!itemRecord) {
        return '';
      }

      const role = typeof itemRecord.role === 'string' ? itemRecord.role : null;
      if (role && role !== 'assistant') {
        return '';
      }

      const contentText = extractTextFromContent(itemRecord.content);
      if (contentText) {
        return contentText;
      }
      if (typeof itemRecord.text === 'string') {
        return itemRecord.text;
      }
      if (typeof itemRecord.output_text === 'string') {
        return itemRecord.output_text;
      }
      return '';
    })
    .join('');
}

function extractTextFromEvent(event: unknown): string {
  const eventRecord = asRecord(event);
  if (!eventRecord) {
    return '';
  }

  if (typeof eventRecord.text === 'string') {
    return eventRecord.text;
  }
  if (typeof eventRecord.output_text === 'string') {
    return eventRecord.output_text;
  }

  const itemRecord = asRecord(eventRecord.item);
  if (itemRecord) {
    return extractTextFromTurn({ output: [itemRecord] });
  }

  return extractTextFromContent(eventRecord.content);
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

  const messageRecord = asRecord(payloadRecord.message);
  if (messageRecord) {
    const messageText = extractTextFromContent(messageRecord.content);
    if (normalizeText(messageText)) {
      return messageText;
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
  if (!messageRecord || typeof messageRecord.from !== 'string') {
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

async function main() {
  console.log('Starting aiteam v2 (Headless Architecture)...');
  
  let hub: CentralHub;
  try {
    hub = new CentralHub(PORT);
  } catch (err) {
    console.error('Failed to start Hub server:', err);
    process.exit(1);
  }
  
  const hubUrl = `ws://localhost:${PORT}`;
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
    output: process.stdout
  });

  let isShuttingDown = false;

  function promptUser() {
    if (isShuttingDown) return;
    rl.question('You> ', (line) => {
      if (isShuttingDown) return;
      const match = line.match(/^@(\w+)\s+([\s\S]*)$/);
      if (match) {
        const target = match[1];
        let payload: any = match[2];
        let eventType = 'prompt';

                // Just send as a normal prompt to the target. Adapters should handle their own CLI specifics.
                ws.send(JSON.stringify({
                    from: 'lead',
                    to: target,
                    eventType,
                    payload
                }));      } else if (line.trim() === 'exit' || line.trim() === 'quit') {
        cleanup();
        return;
      } else {
        console.log('Invalid format. Use "@agent message".');
      }
      // Re-prompt immediately (in a real async flow we'd wait for response, but for now we just loop)
      promptUser();
    });
  }

  ws.on('open', () => {
    ws.send(JSON.stringify({ type: 'identify', id: 'lead' }));
    console.log('\n--- aiteam CLI ---');
    console.log('Available agents: codex, claude, gemini');
    console.log('Type "@agent_name message" to send a prompt. Example: @claude hello');
    promptUser();
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
    try {
      const parsed = JSON.parse(data.toString());
      displayMessage = formatCliMessage(parsed);
    } catch {
      return;
    }

    if (!displayMessage) {
      return;
    }

    readline.clearLine(process.stdout, 0);
    readline.cursorTo(process.stdout, 0);
    console.log(`\n[${displayMessage.from}] ${displayMessage.text}`);
    rl.prompt(true);
  });

  function cleanup() {
    if (isShuttingDown) return;
    isShuttingDown = true;
    console.log('\nShutting down...');
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

main().catch(console.error);
