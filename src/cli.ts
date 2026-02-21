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
  
  // 1. Start Hub
  const hub = new CentralHub(PORT);
  
  // 2. Start Adapters
  const hubUrl = `ws://localhost:${PORT}`;
  const codex = new CodexAdapter(hubUrl, 'codex');
  const claude = new ClaudeAdapter(hubUrl, 'claude');
  const gemini = new GeminiAdapter(hubUrl, 'gemini');

  await Promise.all([
    codex.start().catch(e => console.error('Codex failed to start', e)),
    claude.start().catch(e => console.error('Claude failed to start', e)),
    gemini.start().catch(e => console.error('Gemini failed to start', e))
  ]);

  // 3. Start CLI Client (Lead Agent)
  const ws = new WebSocket(hubUrl);
  
  ws.on('open', () => {
    ws.send(JSON.stringify({ type: 'identify', id: 'lead' }));
    console.log("\\n--- aiteam CLI ---");
    console.log('Available agents: codex, claude, gemini');
    console.log('Type "@agent_name message" to send a prompt. Example: @claude hello');
    promptUser();
  });

  const rl = readline.createInterface({
    input: process.stdin,
    output: process.stdout
  });

  function promptUser() {
    rl.question('You> ', (line) => {
      const match = line.match(/^@(\w+)\s+(.*)$/);
      if (match) {
        const target = match[1];
        const payload = match[2];
        
        ws.send(JSON.stringify({
            from: 'lead',
            to: target,
            eventType: 'prompt',
            payload: payload
        }));
      } else if (line.trim() === 'exit' || line.trim() === 'quit') {
        cleanup();
        return;
      } else {
        console.log('Invalid format. Use "@agent message".');
      }
      promptUser();
    });
  }

  ws.on('message', (data) => {
    try {
        const msg = JSON.parse(data.toString());
        // Simple formatting for the UI
        let output = '';
        if (msg.payload && typeof msg.payload === 'object') {
            // Try to extract readable text
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
        console.log(`\\n[${msg.from}] ${output}`);
        rl.prompt(true);
    } catch (e) {
        console.log(`\\n[Raw] ${data.toString()}`);
        rl.prompt(true);
    }
  });

  function cleanup() {
    console.log('\\nShutting down...');
    rl.close();
    ws.close();
    codex.stop();
    claude.stop();
    gemini.stop();
    hub.stop();
    process.exit(0);
  }

  process.on('SIGINT', cleanup);
  process.on('SIGTERM', cleanup);
}

main().catch(console.error);
