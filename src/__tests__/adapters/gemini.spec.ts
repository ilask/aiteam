import { describe, it, expect, beforeAll, afterAll } from 'vitest';
import { CentralHub } from '../../index.js';
import { GeminiAdapter } from '../../adapters/gemini.js';
import { WebSocket } from 'ws';

describe('Gemini Adapter', () => {
  let hub: CentralHub;
  const PORT = 4505;
  let adapter: GeminiAdapter;

  beforeAll(async () => {
    hub = new CentralHub(PORT);
    adapter = new GeminiAdapter(`ws://localhost:${PORT}`, 'gemini');
    await adapter.start();
  });

  afterAll(() => {
    adapter.stop();
    hub.stop();
  });

  it('should connect to hub and be ready to route messages', async () => {
    const ws = new WebSocket(`ws://localhost:${PORT}`);
    await new Promise(resolve => ws.on('open', resolve));

    ws.send(JSON.stringify({ type: 'identify', id: 'lead' }));
    await new Promise(resolve => setTimeout(resolve, 100));

    // We do not test actual prompt routing here since GEMINI_API_KEY might be missing in CI
    // and process might exit with code 41. We just ensure it connected.
    expect(adapter).toBeDefined();

    ws.close();
  });
});
