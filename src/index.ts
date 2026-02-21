#!/usr/bin/env node
import { WebSocketServer, WebSocket } from 'ws';
import { z } from 'zod';

const MessageSchema = z.object({
  id: z.string().uuid().optional(),
  from: z.string(),
  to: z.string(),
  eventType: z.string(),
  timestamp: z.number().optional(),
  payload: z.any()
});

type AgentMessage = z.infer<typeof MessageSchema>;

export class CentralHub {
  private wss: WebSocketServer;
  private connections: Map<string, WebSocket> = new Map();

  constructor(port: number) {
    this.wss = new WebSocketServer({ port });
    
    this.wss.on('connection', (ws, req) => {
      // Basic handshake: wait for identify message
      let agentId: string | null = null;
      
      ws.on('message', (data) => {
        try {
          const parsed = JSON.parse(data.toString());
          if (parsed.type === 'identify' && typeof parsed.id === 'string') {
            if (this.connections.has(parsed.id)) {
                ws.send(JSON.stringify({ error: 'Agent ID already connected' }));
                ws.close();
                return;
            }
            agentId = parsed.id as string;
            this.connections.set(agentId, ws);
            console.log(`Agent connected: ${agentId}`);
            return;
          }
          
          if (!agentId) {
            ws.send(JSON.stringify({ error: 'Must identify first' }));
            return;
          }

          const validation = MessageSchema.safeParse(parsed);
          if (!validation.success) {
            ws.send(JSON.stringify({ error: 'Invalid message format', details: validation.error }));
            return;
          }

          const message = validation.data;
          
          if (message.from !== agentId) {
            ws.send(JSON.stringify({ error: 'Spoofed identity detected', details: `You are identified as ${agentId}` }));
            return;
          }

          this.routeMessage(message, ws);

        } catch (err) {
          ws.send(JSON.stringify({ error: 'Invalid JSON' }));
        }
      });

      ws.on('close', () => {
        if (agentId) {
          this.connections.delete(agentId);
          console.log(`Agent disconnected: ${agentId}`);
        }
      });
    });
  }

  private routeMessage(message: AgentMessage, senderWs: WebSocket) {
    console.log(`Routing from ${message.from} to ${message.to}`);
    const targetWs = this.connections.get(message.to);
    
    if (targetWs && targetWs.readyState === WebSocket.OPEN) {
      targetWs.send(JSON.stringify(message));
    } else {
      console.warn(`Target ${message.to} not connected.`);
      senderWs.send(JSON.stringify({ error: 'Delivery failed', target: message.to, reason: 'Target offline' }));
    }
  }

  public stop() {
    this.wss.close();
  }
}

// Start the server if this script is executed directly
if (process.argv[1] === new URL(import.meta.url).pathname) {
  const port = process.env.PORT ? parseInt(process.env.PORT, 10) : 4501;
  const hub = new CentralHub(port);
  console.log(`Central Hub listening on ws://localhost:${port}`);
}
