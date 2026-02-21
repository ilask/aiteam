import { spawn, ChildProcess } from 'child_process';
import * as readline from 'readline';
import { WebSocket } from 'ws';
import { randomUUID } from 'crypto';

export class GeminiAdapter {
  private geminiProcess: ChildProcess | null = null;
  private hubWs: WebSocket | null = null;
  private rl: readline.Interface | null = null;
  private agentId: string;
  private hubUrl: string;
  private isStopping: boolean = false;
  
  // Track requests for routing responses back
  // Map of messageId -> originating agent
  private requestMap: Map<string, string> = new Map();

  constructor(hubUrl: string, agentId: string = 'gemini') {
    this.hubUrl = hubUrl;
    this.agentId = agentId;
  }

  public async start() {
    return new Promise<void>((resolve, reject) => {
      this.hubWs = new WebSocket(this.hubUrl);

      this.hubWs.on('open', () => {
        console.log(`[GeminiAdapter] Connected to Hub at ${this.hubUrl}`);
        this.hubWs?.send(JSON.stringify({ type: 'identify', id: this.agentId }));
        
        try {
          this.startGeminiProcess();
          resolve();
        } catch (e) {
          reject(e);
        }
      });

      this.hubWs.on('message', (data) => {
        this.handleHubMessage(data.toString());
      });

      this.hubWs.on('error', (err) => {
        console.error(`[GeminiAdapter] Hub WS error:`, err);
        if (!this.isStopping) reject(err);
      });

      this.hubWs.on('close', () => {
        console.log(`[GeminiAdapter] Hub WS closed`);
        this.stop();
      });
    });
  }

  private startGeminiProcess() {
    console.log('[GeminiAdapter] Starting gemini process (stdio streaming)');
    
    const cmd = 'gemini';
    
    // Gemini CLI accepts -o stream-json for output, and reads text from stdin
    this.geminiProcess = spawn(cmd, ['-o', 'stream-json'], {
      stdio: ['pipe', 'pipe', 'inherit'],
      shell: process.platform === 'win32'
    });

    this.geminiProcess.on('error', (err) => {
      console.error('[GeminiAdapter] Failed to spawn Gemini:', err);
      this.stop();
    });

    if (!this.geminiProcess.stdout || !this.geminiProcess.stdin) {
      throw new Error('Failed to attach to Gemini stdio');
    }

    this.geminiProcess.stdin.on('error', (err) => {
       console.error('[GeminiAdapter] Gemini stdin error:', err);
    });

    this.rl = readline.createInterface({
      input: this.geminiProcess.stdout,
      terminal: false
    });

    this.rl.on('line', (line) => {
      this.handleGeminiMessage(line);
    });

    this.geminiProcess.on('exit', (code) => {
      console.log(`[GeminiAdapter] Gemini process exited with code ${code}`);
      this.stop();
    });
  }

  private handleHubMessage(data: string) {
    try {
      const msg = JSON.parse(data);
      if ((msg.eventType === 'prompt' || msg.eventType === 'delegate') && msg.payload) {
        if (msg.id) {
            this.requestMap.set(msg.id, msg.returnTo || msg.from);
        }
        // Send to Gemini with implicit context injection if needed.
        this.sendToGemini(msg.payload);
      } else if (msg.eventType === 'raw' && msg.payload) {
        if (msg.id) {
            this.requestMap.set(msg.id, msg.returnTo || msg.from);
        }
        this.sendToGemini(msg.payload);
      }
    } catch (e) {
      console.error('[GeminiAdapter] Failed to parse hub message:', e);
    }
  }

  private handleGeminiMessage(line: string) {
    try {
      const parsed = JSON.parse(line);
      
      // Attempt to extract text to check for delegation
      let textContent = '';
      if (parsed.message && parsed.message.content) {
          const content = parsed.message.content;
          textContent = typeof content === 'string' ? content : (Array.isArray(content) ? content.map((c:any) => c.text).join('') : JSON.stringify(content));
      } else if (parsed.result) {
          textContent = typeof parsed.result === 'string' ? parsed.result : JSON.stringify(parsed.result);
      }

      let to = 'lead';
      let eventType = parsed.type || 'gemini_event';
      let payload = parsed;

      // Check if this is an explicit delegation
      const match = textContent.match(/^@(\w+)\s+([\s\S]*)$/);
      if (match) {
          to = match[1];
          eventType = 'delegate';
          payload = match[2];
          console.log(`[GeminiAdapter] Intercepted delegation to ${to}`);
      } else {
          // Default to the first mapped requester (like Claude adapter)
          if (this.requestMap.size > 0) {
              to = Array.from(this.requestMap.values())[0];
              if (parsed.type === 'result' || parsed.type === 'finish') {
                  this.requestMap.clear();
              }
          }
      }

      const hubMsg = {
        id: randomUUID(),
        from: this.agentId,
        to: to,
        eventType: eventType,
        returnTo: this.agentId,
        timestamp: Date.now(),
        payload: payload
      };

      if (this.hubWs && this.hubWs.readyState === WebSocket.OPEN) {
        this.hubWs.send(JSON.stringify(hubMsg));
      }
    } catch (e) {
      // If output is not JSON, might be raw text from early startup
      console.error('[GeminiAdapter] Non-JSON from Gemini:', line);
    }
  }

  private sendToGemini(payload: string) {
    if (this.geminiProcess && this.geminiProcess.stdin && !this.geminiProcess.stdin.destroyed) {
      // Send raw text to Gemini stdin
      this.geminiProcess.stdin.write(payload + "\\n");
    }
  }

  public stop() {
    if (this.isStopping) return;
    this.isStopping = true;
    
    if (this.rl) {
        this.rl.close();
        this.rl = null;
    }
    if (this.geminiProcess) {
        this.geminiProcess.kill();
        this.geminiProcess = null;
    }
    if (this.hubWs) {
        this.hubWs.close();
        this.hubWs = null;
    }
  }
}
