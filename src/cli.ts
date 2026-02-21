#!/usr/bin/env node
import { CentralHub } from './index.js';
import { CodexAdapter } from './adapters/codex.js';
import { ClaudeAdapter } from './adapters/claude.js';
import { GeminiAdapter } from './adapters/gemini.js';
import { WebSocket } from 'ws';
import * as readline from 'readline';

const PORT = process.env.PORT ? parseInt(process.env.PORT, 10) : 4501;

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
    try {
        const msg = JSON.parse(data.toString());
        let output = '';
        if (msg.payload && typeof msg.payload === 'object') {
            if (msg.payload.message && msg.payload.message.content) {
                const content = msg.payload.message.content;
                output = Array.isArray(content) ? content.map((c:any) => c.text).join('') : content;
            } else if (msg.payload.result) {
                output = typeof msg.payload.result === 'string' ? msg.payload.result : JSON.stringify(msg.payload.result);
            } else {
                output = JSON.stringify(msg.payload);
            }
        } else {
            output = msg.payload;
        }

        readline.clearLine(process.stdout, 0);
        readline.cursorTo(process.stdout, 0);
        console.log(`\n[${msg.from}] ${output}`);
        rl.prompt(true);
    } catch (e) {
        readline.clearLine(process.stdout, 0);
        readline.cursorTo(process.stdout, 0);
        console.log(`\n[Raw] ${data.toString()}`);
        rl.prompt(true);
    }
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
