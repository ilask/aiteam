import { describe, it, expect, beforeAll, afterAll } from 'vitest';
import { WebSocket } from 'ws';
import { CentralHub } from '../index.js';

describe('Central Hub WebSocket Server', () => {
  let hub: CentralHub;
  const PORT = 4502; // Use a different port for testing

  beforeAll(() => {
    hub = new CentralHub(PORT);
  });

  afterAll(() => {
    hub.stop();
  });

  it('should accept connections and route messages', async () => {
    const ws1 = new WebSocket(`ws://localhost:${PORT}`);
    const ws2 = new WebSocket(`ws://localhost:${PORT}`);

    // Helper to wait for open
    const waitForOpen = (ws: WebSocket) => new Promise(resolve => ws.on('open', resolve));
    await Promise.all([waitForOpen(ws1), waitForOpen(ws2)]);

    // Identify
    ws1.send(JSON.stringify({ type: 'identify', id: 'agent1' }));
    ws2.send(JSON.stringify({ type: 'identify', id: 'agent2' }));

    // Wait briefly for identification to process
    await new Promise(resolve => setTimeout(resolve, 50));

    // Send a message from agent1 to agent2
    const message = {
      from: 'agent1',
      to: 'agent2',
      eventType: 'chat',
      payload: 'Hello from agent1'
    };

    const receivedMessage = new Promise((resolve) => {
      ws2.on('message', (data) => {
        resolve(JSON.parse(data.toString()));
      });
    });

    ws1.send(JSON.stringify(message));

    const result = await receivedMessage;
    expect(result).toEqual(message);

    ws1.close();
    ws2.close();
  });
});
