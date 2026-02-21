import { spawn, ChildProcess } from 'child_process';
import * as readline from 'readline';
import { WebSocket } from 'ws';
import { randomUUID } from 'crypto';

export class CodexAdapter {
  private codexProcess: ChildProcess | null = null;
  private hubWs: WebSocket | null = null;
  private rl: readline.Interface | null = null;
  private agentId: string;
  private hubUrl: string;
  private isStopping: boolean = false;
  
  // Track JSON-RPC state
  private isInitialized: boolean = false;
  private initMessageId: string | null = null;
  private currentThreadId: string | null = null;
  
  // Track who requested what: RPC ID -> Originating Agent ID
  private requestMap: Map<string | number, string> = new Map();
  private pendingPrompts: { id: string, from: string, text: string }[] = [];

  constructor(hubUrl: string, agentId: string = 'codex') {
    this.hubUrl = hubUrl;
    this.agentId = agentId;
  }

  public async start() {
    return new Promise<void>((resolve, reject) => {
      this.hubWs = new WebSocket(this.hubUrl);

      this.hubWs.on('open', () => {
        console.log(`[CodexAdapter] Connected to Hub at ${this.hubUrl}`);
        this.hubWs?.send(JSON.stringify({ type: 'identify', id: this.agentId }));
        
        try {
          this.startCodexProcess();
          resolve();
        } catch (e) {
          reject(e);
        }
      });

      this.hubWs.on('message', (data) => {
        this.handleHubMessage(data.toString());
      });

      this.hubWs.on('error', (err) => {
        console.error(`[CodexAdapter] Hub WS error:`, err);
        if (!this.isStopping) reject(err);
      });

      this.hubWs.on('close', () => {
        console.log(`[CodexAdapter] Hub WS closed`);
        this.stop();
      });
    });
  }

  private startCodexProcess() {
    console.log('[CodexAdapter] Starting codex app-server (stdio)');
    
    // Avoid shell: true on Windows to prevent orphan processes
    const cmd = 'codex';
    
    this.codexProcess = spawn(cmd, ['app-server'], {
      stdio: ['pipe', 'pipe', 'inherit'],
      shell: process.platform === 'win32'
    });

    this.codexProcess.on('error', (err) => {
      console.error('[CodexAdapter] Failed to spawn Codex:', err);
      this.stop();
    });

    if (!this.codexProcess.stdout || !this.codexProcess.stdin) {
      throw new Error('Failed to attach to Codex stdio');
    }

    this.codexProcess.stdin.on('error', (err) => {
       console.error('[CodexAdapter] Codex stdin error:', err);
    });

    this.rl = readline.createInterface({
      input: this.codexProcess.stdout,
      terminal: false
    });

    this.rl.on('line', (line) => {
      this.handleCodexMessage(line);
    });

    this.codexProcess.on('exit', (code) => {
      console.log(`[CodexAdapter] Codex process exited with code ${code}`);
      this.stop();
    });

    // Send initialize request
    this.initMessageId = randomUUID();
    this.sendToCodex({
      jsonrpc: "2.0",
      id: this.initMessageId,
      method: "initialize",
      params: { clientInfo: { name: "aiteam", version: "2.0.0" }, capabilities: {} }
    });
  }

    private handleHubMessage(data: string) {
      try {
        const msg = JSON.parse(data);
        if (msg.eventType === 'rpc' && msg.payload) {
          // Track the request so we can route the response back
          if (msg.payload.id !== undefined) {
              this.requestMap.set(msg.payload.id, msg.from);
          }
          this.sendToCodex(msg.payload);
        } else if ((msg.eventType === 'prompt' || msg.eventType === 'delegate') && msg.payload) {
          // The user/agent sent a plain text prompt. We need to wrap it in a JSON-RPC turn/start.
          if (!this.currentThreadId) {
              // Need to create a thread first.
              const threadRequestId = randomUUID();
              this.requestMap.set(threadRequestId, msg.from);
              this.pendingPrompts.push({ id: threadRequestId, from: msg.from, text: msg.payload });
              
              this.sendToCodex({
                  jsonrpc: "2.0",
                  id: threadRequestId,
                  method: "thread/start",
                  params: {}
              });
          } else {
              // Already have a thread, send turn/start
              const turnRequestId = randomUUID();
              this.requestMap.set(turnRequestId, msg.from);
              this.sendToCodex({
                  jsonrpc: "2.0",
                  id: turnRequestId,
                  method: "turn/start",
                  params: {
                      threadId: this.currentThreadId,
                      input: [{ type: "text", text: msg.payload }]
                  }
              });
          }
        }
      } catch (e) {
        console.error('[CodexAdapter] Failed to parse hub message:', e);
      }
    }
    private handleCodexMessage(line: string) {
      try {
        const parsed = JSON.parse(line);
  
        // Handle initialize response
        if (parsed.id === this.initMessageId && !this.isInitialized) {
          this.isInitialized = true;
          this.sendToCodex({
              jsonrpc: "2.0",
              method: "initialized",
              params: {}
          });
          console.log('[CodexAdapter] Codex initialized successfully.');
        }
  
        // Handle thread/start response
        if (parsed.id !== undefined && parsed.result?.thread?.id) {
            this.currentThreadId = parsed.result.thread.id;
            
            // Check if we have pending prompts that triggered this thread start
            const pendingIndex = this.pendingPrompts.findIndex(p => p.id === parsed.id);
            if (pendingIndex !== -1) {
                const pending = this.pendingPrompts.splice(pendingIndex, 1)[0];
                const turnRequestId = randomUUID();
                this.requestMap.set(turnRequestId, pending.from);
                this.sendToCodex({
                    jsonrpc: "2.0",
                    id: turnRequestId,
                    method: "turn/start",
                    params: {
                        threadId: this.currentThreadId,
                        input: [{ type: "text", text: pending.text }]
                    }
                });
                // We do not route the raw thread/start response back to the user, as they just sent a plain prompt
                return; 
            }
        }
  
        // Determine routing destination      let targetAgent = 'lead'; // fallback
      
      if (parsed.id !== undefined && this.requestMap.has(parsed.id)) {
          targetAgent = this.requestMap.get(parsed.id)!;
          this.requestMap.delete(parsed.id); // clean up
      }

      // Determine event type based on JSON-RPC structure
      let eventType = 'rpc_response';
      if (parsed.method && parsed.id === undefined) eventType = 'rpc_notification';
      if (parsed.method && parsed.id !== undefined) eventType = 'rpc_request'; // server-initiated request

      const hubMsg = {
        id: randomUUID(),
        from: this.agentId,
        to: targetAgent, 
        eventType,
        timestamp: Date.now(),
        payload: parsed
      };

      if (this.hubWs && this.hubWs.readyState === WebSocket.OPEN) {
        this.hubWs.send(JSON.stringify(hubMsg));
      }
    } catch (e) {
      console.error('[CodexAdapter] Invalid JSON from Codex:', line);
    }
  }

  private sendToCodex(payload: any) {
    if (this.codexProcess && this.codexProcess.stdin && !this.codexProcess.stdin.destroyed) {
      this.codexProcess.stdin.write(JSON.stringify(payload) + "\n");
    }
  }

  public stop() {
    if (this.isStopping) return;
    this.isStopping = true;
    
    if (this.rl) {
        this.rl.close();
        this.rl = null;
    }
    if (this.codexProcess) {
        this.codexProcess.kill();
        this.codexProcess = null;
    }
    if (this.hubWs) {
        this.hubWs.close();
        this.hubWs = null;
    }
  }
}
