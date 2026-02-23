import { spawn, ChildProcess } from 'child_process';
import * as readline from 'readline';
import { WebSocket } from 'ws';
import { randomUUID } from 'crypto';

const AUTONOMOUS_MODE_DISABLED_VALUES = new Set(['0', 'false', 'off', 'no']);
const ENABLED_VALUES = new Set(['1', 'true', 'on', 'yes']);
const DEFAULT_CLAUDE_PERMISSION_MODE = 'bypassPermissions';

function isAutonomousModeEnabled(rawValue: string | undefined): boolean {
  if (!rawValue) return true;
  return !AUTONOMOUS_MODE_DISABLED_VALUES.has(rawValue.trim().toLowerCase());
}

function isTextOnlyModeEnabled(rawValue: string | undefined): boolean {
  if (!rawValue) return false;
  return ENABLED_VALUES.has(rawValue.trim().toLowerCase());
}

function resolveClaudePermissionMode(rawValue: string | undefined): string {
  const normalized = rawValue?.trim();
  if (!normalized) {
    return DEFAULT_CLAUDE_PERMISSION_MODE;
  }
  return normalized;
}

function buildAutonomousPrompt(agentId: string, originalPrompt: string): string {
  return [
    `[aiteam autonomy mode: ${agentId}]`,
    'Prefer agent-to-agent collaboration before replying to lead.',
    'Delegate tasks with exactly one line: @<agent> <task>.',
    'Send progress updates only when blocked; otherwise send final synthesized result.',
    '',
    'Task:',
    originalPrompt
  ].join('\n');
}

function buildTextOnlyPrompt(agentId: string, originalPrompt: string): string {
  return [
    `[aiteam claude text-only mode: ${agentId}]`,
    'Reply in plain text only.',
    'Do NOT use tools (Read, Write, Edit, MultiEdit, Bash, Glob, Grep).',
    'Do NOT access files or convert paths.',
    '',
    'Task:',
    originalPrompt
  ].join('\n');
}

export class ClaudeAdapter {
  private claudeProcess: ChildProcess | null = null;
  private hubWs: WebSocket | null = null;
  private rl: readline.Interface | null = null;
  private agentId: string;
  private hubUrl: string;
  private isStopping: boolean = false;
  private autonomousModeEnabled: boolean;
  private textOnlyModeEnabled: boolean;
  private claudePermissionMode: string;
  
  // Track requests for routing responses back
  // Map of messageId -> originating agent
  private requestMap: Map<string, string> = new Map();

  constructor(hubUrl: string, agentId: string = 'claude') {
    this.hubUrl = hubUrl;
    this.agentId = agentId;
    this.autonomousModeEnabled = isAutonomousModeEnabled(
      process.env.AITEAM_AUTONOMOUS_MODE
    );
    this.textOnlyModeEnabled = isTextOnlyModeEnabled(
      process.env.AITEAM_CLAUDE_TEXT_ONLY
    );
    this.claudePermissionMode = resolveClaudePermissionMode(
      process.env.AITEAM_CLAUDE_PERMISSION_MODE
    );
  }

  public async start() {
    return new Promise<void>((resolve, reject) => {
      this.hubWs = new WebSocket(this.hubUrl);

      this.hubWs.on('open', () => {
        // console.debug(`[ClaudeAdapter] Connected to Hub at ${this.hubUrl}`);
        this.hubWs?.send(JSON.stringify({ type: 'identify', id: this.agentId }));
        
        try {
          this.startClaudeProcess();
          resolve();
        } catch (e) {
          reject(e);
        }
      });

      this.hubWs.on('message', (data) => {
        this.handleHubMessage(data.toString());
      });

      this.hubWs.on('error', (err) => {
        console.error(`[ClaudeAdapter] Hub WS error:`, err);
        if (!this.isStopping) reject(err);
      });

      this.hubWs.on('close', () => {
        // console.debug(`[ClaudeAdapter] Hub WS closed`);
        this.stop();
      });
    });
  }

  private startClaudeProcess() {
    if (this.claudeProcess && this.claudeProcess.stdin && !this.claudeProcess.stdin.destroyed) {
      return;
    }

    // console.debug('[ClaudeAdapter] Starting claude process (stdio streaming)');
    
    const cmd = 'claude';
    const args = [
      '--print',
      '--verbose',
      '--input-format=stream-json',
      '--output-format=stream-json',
      '--permission-mode',
      this.claudePermissionMode
    ];

    this.claudeProcess = spawn(cmd, args, {
      stdio: ['pipe', 'pipe', 'ignore'],
      shell: process.platform === 'win32' // Required for some windows environments to find global npm binaries
    });

    this.claudeProcess.on('error', (err) => {
      console.error('[ClaudeAdapter] Failed to spawn Claude:', err);
      this.detachClaudeIo();
    });

    if (!this.claudeProcess.stdout || !this.claudeProcess.stdin) {
      throw new Error('Failed to attach to Claude stdio');
    }

    this.claudeProcess.stdin.on('error', (err) => {
       console.error('[ClaudeAdapter] Claude stdin error:', err);
    });

    this.rl = readline.createInterface({
      input: this.claudeProcess.stdout,
      terminal: false
    });

    this.rl.on('line', (line) => {
      this.handleClaudeMessage(line);
    });

    this.claudeProcess.on('exit', (code) => {
      // console.debug(`[ClaudeAdapter] Claude process exited with code ${code}`);
      this.detachClaudeIo();
      if (!this.isStopping) {
        // Keep adapter connected to Hub. The process is spawned lazily on the next prompt.
      }
    });
  }

  private ensureClaudeProcess() {
    if (this.isStopping) {
      return;
    }
    const hasActiveStdin =
      this.claudeProcess !== null &&
      this.claudeProcess.stdin !== null &&
      !this.claudeProcess.stdin.destroyed;
    if (!hasActiveStdin) {
      this.startClaudeProcess();
    }
  }

  private detachClaudeIo() {
    if (this.rl) {
      this.rl.close();
      this.rl = null;
    }
    this.claudeProcess = null;
  }

  private handleHubMessage(data: string) {
    try {
      const msg = JSON.parse(data);
      if ((msg.eventType === 'prompt' || msg.eventType === 'delegate') && msg.payload) {
        if (msg.id) {
            this.requestMap.set(msg.id, msg.returnTo || msg.from);
        }
        const promptText =
          typeof msg.payload === 'string' ? msg.payload : JSON.stringify(msg.payload);
        let content = promptText;
        if (this.autonomousModeEnabled && msg.from === 'lead') {
          content = buildAutonomousPrompt(this.agentId, content);
        }
        if (this.textOnlyModeEnabled) {
          content = buildTextOnlyPrompt(this.agentId, content);
        }
        this.ensureClaudeProcess();
        // Send to Claude with hidden system prompt instructions if it's the first message
        this.sendToClaude({
            type: "user",
            message: {
                role: "user",
                content
            }
        });
      } else if (msg.eventType === 'raw' && msg.payload) {
        if (msg.id) {
            this.requestMap.set(msg.id, msg.returnTo || msg.from);
        }
        this.ensureClaudeProcess();
        this.sendToClaude(msg.payload);
      }
    } catch (e) {
      console.error('[ClaudeAdapter] Failed to parse hub message:', e);
    }
  }

  private handleClaudeMessage(line: string) {
    try {
      const parsed = JSON.parse(line);
      
      // Attempt to extract text to check for delegation
      let textContent = '';
      if (parsed.type === 'assistant' && parsed.message && parsed.message.content) {
          const content = parsed.message.content;
          textContent = Array.isArray(content) ? content.map((c:any) => c.text).join('') : content;
      }

      let to = 'lead';
      let eventType = parsed.type || 'claude_event';
      let payload = parsed;

      // Check if this is an explicit delegation
      const match = textContent.match(/^@(\w+)\s+([\s\S]*)$/);
      if (match) {
          to = match[1];
          eventType = 'delegate';
          payload = match[2];
          // console.debug(`[ClaudeAdapter] Intercepted delegation to ${to}`);
      } else {
          // If not a delegation, try to map back to the original requester.
          // Since Claude CLI stream-json doesn't natively return our correlation IDs,
          // we fallback to 'lead' or the most recent requester if we want to be hacky,
          // but for true multi-agent, we need the CLI to echo back IDs.
          // For now, if we have exactly one requester mapped, we use it.
          // Otherwise default to lead.
          if (this.requestMap.size > 0) {
              // Just grab the first one for this basic implementation
              to = Array.from(this.requestMap.values())[0];
              // If it's a final result, clean up the map
              if (parsed.type === 'result') {
                  this.requestMap.clear();
              }
          }
      }

      const hubMsg = {
        id: randomUUID(),
        from: this.agentId,
        to: to,
        eventType: eventType,
        returnTo: this.agentId, // Tell the delegatee to reply to Claude
        timestamp: Date.now(),
        payload: payload
      };

      if (this.hubWs && this.hubWs.readyState === WebSocket.OPEN) {
        this.hubWs.send(JSON.stringify(hubMsg));
      }
    } catch (e) {
      console.error('[ClaudeAdapter] Invalid JSON from Claude:', line);
    }
  }

  private sendToClaude(payload: any) {
    this.ensureClaudeProcess();
    if (this.claudeProcess && this.claudeProcess.stdin && !this.claudeProcess.stdin.destroyed) {
      this.claudeProcess.stdin.write(JSON.stringify(payload) + "\n");
    }
  }

  public stop() {
    if (this.isStopping) return;
    this.isStopping = true;
    
    if (this.claudeProcess) {
        this.claudeProcess.kill();
    }
    this.detachClaudeIo();
    if (this.hubWs) {
        this.hubWs.close();
        this.hubWs = null;
    }
  }
}
