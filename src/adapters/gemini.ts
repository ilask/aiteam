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
  private currentRequester: string = 'lead';

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
      if (msg.eventType === 'prompt' && msg.payload) {
        this.currentRequester = msg.from;
        this.sendToGemini(msg.payload);
      }
    } catch (e) {
      console.error('[GeminiAdapter] Failed to parse hub message:', e);
    }
  }

  private handleGeminiMessage(line: string) {
    try {
      const parsed = JSON.parse(line);
      
      const hubMsg = {
        id: randomUUID(),
        from: this.agentId,
        to: this.currentRequester, 
        eventType: parsed.type || 'gemini_event',
        timestamp: Date.now(),
        payload: parsed
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
