import { describe, it, expect, beforeAll, afterAll } from 'vitest';
import { CentralHub } from '../../index.js';
import { CodexAdapter } from '../../adapters/codex.js';
import { WebSocket } from 'ws';
import { randomUUID } from 'crypto';

describe('E2E: Inter-Agent Router (Agent Teams)', () => {
  let hub: CentralHub;
  let codex: CodexAdapter;
  const PORT = 4515;

  beforeAll(async () => {
    hub = new CentralHub(PORT);
    const hubUrl = `ws://localhost:${PORT}`;
    codex = new CodexAdapter(hubUrl, 'codex');
    await codex.start();
  });

  afterAll(() => {
    codex.stop();
    hub.stop();
  });

  it('Agents can autonomously delegate tasks', async () => {
    // We will use a Mock Agent connected via WebSocket to simulate Claude/Gemini
    // intercepting and delegating a message to Codex.
    const mockAgentWs = new WebSocket(`ws://localhost:${PORT}`);
    await new Promise(resolve => mockAgentWs.on('open', resolve));
    mockAgentWs.send(JSON.stringify({ type: 'identify', id: 'mockAgent' }));

    // Wait for identify
    await new Promise(resolve => setTimeout(resolve, 50));

    // The Mock Agent intercepts a message and decides to delegate to Codex
    // Simulate what the Adapter Message Interceptor does:
    const delegationMsg = {
        id: randomUUID(),
        from: 'mockAgent',
        to: 'codex', // Hub will route this to Codex
        eventType: 'rpc', // Codex expects 'rpc' currently from hub
        returnTo: 'mockAgent', // Instruct Codex to send the response back to mockAgent (needs adapter support, but hub routes based on 'to')
        payload: {
            jsonrpc: "2.0",
            id: "test-echo-1",
            method: "turn/start",
            params: { prompt: "echo HELO" }
        }
    };

    const codexResponse = new Promise<any>((resolve, reject) => {
        const timeout = setTimeout(() => reject(new Error('Timeout waiting for Codex delegation response')), 15000);
        mockAgentWs.on('message', (data) => {
            const msg = JSON.parse(data.toString());
            // mockAgent receives a response from codex
            if (msg.from === 'codex') {
                clearTimeout(timeout);
                resolve(msg);
            }
        });
    });

    mockAgentWs.send(JSON.stringify(delegationMsg));

    const response = await codexResponse;
    
    // Assert that the mock agent received a reply directly from codex
    expect(response.from).toBe('codex');
    expect(response.to).toBe('mockAgent'); // Codex Adapter uses requestMap to send it back to 'mockAgent'
    expect(response.eventType).toBe('rpc_response');

    mockAgentWs.close();
  }, 20000);
});
