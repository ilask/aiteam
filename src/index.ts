#!/usr/bin/env node
import { WebSocketServer, WebSocket } from 'ws';
import { z } from 'zod';

const MessageSchema = z.object({
  id: z.string().uuid().optional(),
  from: z.string(),
  to: z.string(),
  eventType: z.string(),
  timestamp: z.number().optional(),
  threadId: z.string().optional(),
  inReplyTo: z.string().optional(),
  returnTo: z.string().optional(),
  payload: z.any()
});

type AgentMessage = z.infer<typeof MessageSchema>;

type RoutePairSnapshot = {
  from: string;
  to: string;
  count: number;
};

type RouteEventSnapshot = {
  eventType: string;
  count: number;
};

export type HubStatusSnapshot = {
  connectedAgents: string[];
  routePairs: RoutePairSnapshot[];
  routeEvents: RouteEventSnapshot[];
};

export class CentralHub {
  private wss: WebSocketServer;
  private connections: Map<string, WebSocket> = new Map();
  private routePairCounts: Map<string, number> = new Map();
  private routeEventCounts: Map<string, number> = new Map();

  constructor(port: number) {
    this.wss = new WebSocketServer({ port });
    this.wss.on('error', (err) => {
      console.error('[CentralHub] WebSocket server error:', err);
    });
    
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
            // console.debug(`Agent connected: ${agentId}`);
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
          // console.debug(`Agent disconnected: ${agentId}`);
        }
      });
    });
  }

  private routeMessage(message: AgentMessage, senderWs: WebSocket) {
    // console.debug(`Routing from ${message.from} to ${message.to}`);
    const targetWs = this.connections.get(message.to);
    
    if (targetWs && targetWs.readyState === WebSocket.OPEN) {
      this.incrementRouteCounters(message.from, message.to, message.eventType);
      targetWs.send(JSON.stringify(message));
    } else {
      console.warn(`Target ${message.to} not connected.`);
      senderWs.send(JSON.stringify({ error: 'Delivery failed', target: message.to, reason: 'Target offline' }));
    }
  }

  private incrementRouteCounters(from: string, to: string, eventType: string) {
    const pairKey = `${from}\u0000${to}`;
    this.routePairCounts.set(pairKey, (this.routePairCounts.get(pairKey) ?? 0) + 1);

    const normalizedEventType = eventType.trim() || 'unknown';
    this.routeEventCounts.set(
      normalizedEventType,
      (this.routeEventCounts.get(normalizedEventType) ?? 0) + 1
    );
  }

  public isConnected(agentId: string): boolean {
    const ws = this.connections.get(agentId);
    return ws !== undefined && ws.readyState === WebSocket.OPEN;
  }

  public getStatusSnapshot(): HubStatusSnapshot {
    const connectedAgents = Array.from(this.connections.entries())
      .filter(([, ws]) => ws.readyState === WebSocket.OPEN)
      .map(([agentId]) => agentId)
      .sort();

    const routePairs = Array.from(this.routePairCounts.entries())
      .map(([key, count]) => {
        const [from, to] = key.split('\u0000');
        return { from, to, count };
      })
      .sort((a, b) => {
        if (a.from !== b.from) return a.from.localeCompare(b.from);
        if (a.to !== b.to) return a.to.localeCompare(b.to);
        return a.count - b.count;
      });

    const routeEvents = Array.from(this.routeEventCounts.entries())
      .map(([eventType, count]) => ({ eventType, count }))
      .sort((a, b) => a.eventType.localeCompare(b.eventType));

    return {
      connectedAgents,
      routePairs,
      routeEvents
    };
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
