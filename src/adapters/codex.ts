import { spawn, ChildProcess } from 'child_process';
import * as readline from 'readline';
import { WebSocket } from 'ws';
import { randomUUID } from 'crypto';

type JsonRecord = Record<string, unknown>;
const AUTONOMOUS_MODE_DISABLED_VALUES = new Set(['0', 'false', 'off', 'no']);
const SUPPORTED_TEAM_AGENT_IDS = new Set(['codex', 'claude', 'gemini']);

export function isCodexAutonomousModeEnabled(rawValue: string | undefined): boolean {
  if (!rawValue) return true;
  return !AUTONOMOUS_MODE_DISABLED_VALUES.has(rawValue.trim().toLowerCase());
}

export function buildCodexAutonomousPrompt(agentId: string, originalPrompt: string): string {
  return [
    `[aiteam autonomy mode: ${agentId}]`,
    'Prefer agent-to-agent collaboration before replying to lead.',
    'Delegate tasks with exactly one line: @<agent> <task>.',
    'Do NOT use internal collab tools (spawnAgent, wait, closeAgent) or external-agent simulation.',
    'Use only @claude / @gemini delegation lines so the aiteam hub can route tasks.',
    'Allowed external agent IDs for delegation: codex, claude, gemini.',
    'Do not use @worker, @explorer, @default, or any unknown agent IDs.',
    'Send progress updates only when blocked; otherwise send final synthesized result.',
    '',
    'Task:',
    originalPrompt
  ].join('\n');
}

export function isSupportedTeamAgentId(agentId: string): boolean {
  return SUPPORTED_TEAM_AGENT_IDS.has(agentId);
}

export function extractSupportedDelegationFromCodexPayload(
  payload: unknown
): {
  to: string;
  task: string;
} | null {
  const supportedDelegations = extractSupportedDelegationsFromCodexPayload(payload);
  if (supportedDelegations.length === 0) {
    return null;
  }
  return supportedDelegations[0];
}

export function extractSupportedDelegationsFromCodexPayload(
  payload: unknown
): Array<{
  to: string;
  task: string;
}> {
  return extractDelegationsFromCodexPayload(payload).filter((delegation) =>
    isSupportedTeamAgentId(delegation.to)
  );
}

function asRecord(value: unknown): JsonRecord | null {
  if (value && typeof value === 'object' && !Array.isArray(value)) {
    return value as JsonRecord;
  }
  return null;
}

function extractTextFromContent(content: unknown): string {
  if (typeof content === 'string') {
    return content;
  }
  if (!Array.isArray(content)) {
    return '';
  }

  return content
    .map((part) => {
      if (typeof part === 'string') {
        return part;
      }
      const record = asRecord(part);
      if (!record) {
        return '';
      }
      if (typeof record.text === 'string') {
        return record.text;
      }
      if (typeof record.output_text === 'string') {
        return record.output_text;
      }
      return '';
    })
    .join('');
}

function extractTextFromTurn(turn: unknown): string {
  const record = asRecord(turn);
  if (!record) {
    return '';
  }

  const output = Array.isArray(record.output) ? record.output : [];
  return output
    .map((item) => {
      const itemRecord = asRecord(item);
      if (!itemRecord) {
        return '';
      }
      const role = typeof itemRecord.role === 'string' ? itemRecord.role.toLowerCase() : '';
      if (role !== 'assistant') {
        return '';
      }
      if (typeof itemRecord.text === 'string') {
        return itemRecord.text;
      }
      if (typeof itemRecord.output_text === 'string') {
        return itemRecord.output_text;
      }
      return extractTextFromContent(itemRecord.content);
    })
    .join('');
}

export function extractDelegationFromCodexPayload(
  payload: unknown
): {
  to: string;
  task: string;
} | null {
  const delegations = extractDelegationsFromCodexPayload(payload);
  return delegations.length > 0 ? delegations[0] : null;
}

export function extractDelegationsFromCodexPayload(
  payload: unknown
): Array<{
  to: string;
  task: string;
}> {
  const record = asRecord(payload);
  if (!record) {
    return [];
  }

  const textCandidates: string[] = [];
  if (typeof record.message === 'string') {
    textCandidates.push(record.message);
  }
  if (typeof record.text === 'string') {
    textCandidates.push(record.text);
  }

  const params = asRecord(record.params);
  if (params) {
    const msg = asRecord(params.msg);
    if (msg) {
      if (typeof msg.message === 'string') {
        textCandidates.push(msg.message);
      }
      if (typeof msg.text === 'string') {
        textCandidates.push(msg.text);
      }
      if (typeof msg.last_agent_message === 'string') {
        textCandidates.push(msg.last_agent_message);
      }
      const msgItem = asRecord(msg.item);
      if (msgItem) {
        if (typeof msgItem.text === 'string') {
          textCandidates.push(msgItem.text);
        }
        textCandidates.push(extractTextFromContent(msgItem.content));
      }
    }

    const item = asRecord(params.item);
    if (item) {
      if (typeof item.text === 'string') {
        textCandidates.push(item.text);
      }
      if (typeof item.last_agent_message === 'string') {
        textCandidates.push(item.last_agent_message);
      }
      textCandidates.push(extractTextFromContent(item.content));
    }

    if (typeof params.last_agent_message === 'string') {
      textCandidates.push(params.last_agent_message);
    }

    textCandidates.push(extractTextFromTurn(params.turn));
  }

  const result = asRecord(record.result);
  if (result) {
    textCandidates.push(extractTextFromTurn(result.turn));
    textCandidates.push(extractTextFromContent(result.content));
    if (typeof result.output_text === 'string') {
      textCandidates.push(result.output_text);
    }
  }

  const delegations: Array<{ to: string; task: string }> = [];
  const seen = new Set<string>();

  for (const text of textCandidates) {
    const lines = text.split(/\r?\n/);
    for (const rawLine of lines) {
      const line = rawLine.trim();
      if (line.length === 0) {
        continue;
      }
      const match = line.match(/^@(\w+)\s+(.+)$/);
      if (!match) {
        continue;
      }
      const to = match[1];
      const task = match[2].trim();
      if (task.length === 0) {
        continue;
      }
      const key = `${to}\u0000${task}`;
      if (seen.has(key)) {
        continue;
      }
      seen.add(key);
      delegations.push({ to, task });
    }
  }

  return delegations;
}

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
  private pendingThreadRequestId: string | null = null;
  private autonomousModeEnabled: boolean;
  
  // Track who requested what: RPC ID -> Originating Agent ID
  private requestMap: Map<string | number, string> = new Map();
  private pendingPrompts: { from: string, returnTo?: string, text: string }[] = [];
  private readonly recentDelegationTimestamps: Map<string, number> = new Map();
  private readonly delegationDedupWindowMs = 30000;

  constructor(hubUrl: string, agentId: string = 'codex') {
    this.hubUrl = hubUrl;
    this.agentId = agentId;
    this.autonomousModeEnabled = isCodexAutonomousModeEnabled(
      process.env.AITEAM_AUTONOMOUS_MODE
    );
  }

  public async start() {
    return new Promise<void>((resolve, reject) => {
      this.hubWs = new WebSocket(this.hubUrl);

      this.hubWs.on('open', () => {
        // console.debug(`[CodexAdapter] Connected to Hub at ${this.hubUrl}`);
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
        // console.debug(`[CodexAdapter] Hub WS closed`);
        this.stop();
      });
    });
  }

  private startCodexProcess() {
    // console.debug('[CodexAdapter] Starting codex app-server (stdio)');
    
    // Keep shell mode on Windows for compatibility with global codex command resolution.
    const cmd = 'codex';
    
    this.codexProcess = spawn(cmd, ['app-server'], {
      stdio: ['pipe', 'pipe', 'ignore'],
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
      // console.debug(`[CodexAdapter] Codex process exited with code ${code}`);
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
          const promptText =
            typeof msg.payload === 'string' ? msg.payload : JSON.stringify(msg.payload);
          const effectivePromptText =
            this.autonomousModeEnabled && msg.from === 'lead'
              ? buildCodexAutonomousPrompt(this.agentId, promptText)
              : promptText;
          // The user/agent sent a plain text prompt. We need to wrap it in a JSON-RPC turn/start.
          if (!this.currentThreadId) {
              // Need to create a thread first.
              this.pendingPrompts.push({
                from: msg.from,
                returnTo: msg.returnTo,
                text: effectivePromptText
              });
              
              if (!this.pendingThreadRequestId) {
                  this.pendingThreadRequestId = randomUUID();
                  this.sendToCodex({
                      jsonrpc: "2.0",
                      id: this.pendingThreadRequestId,
                      method: "thread/start",
                      params: {}
                  });
              }
          } else {
              // Already have a thread, send turn/start
              const turnRequestId = randomUUID();
              this.requestMap.set(turnRequestId, msg.returnTo || msg.from);
              this.sendToCodex({
                  jsonrpc: "2.0",
                  id: turnRequestId,
                  method: "turn/start",
                  params: {
                      threadId: this.currentThreadId,
                      input: [{ type: "text", text: effectivePromptText }]
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
          // console.debug('[CodexAdapter] Codex initialized successfully.');
        }
  
              // Handle thread/start response
              if (this.pendingThreadRequestId && parsed.id === this.pendingThreadRequestId) {
                  this.pendingThreadRequestId = null;
                  
                  if (parsed.result?.thread?.id) {
                      this.currentThreadId = parsed.result.thread.id;
                      
                      // Process all pending prompts
                      while (this.pendingPrompts.length > 0) {
                          const pending = this.pendingPrompts.shift()!;
                          const turnRequestId = randomUUID();
                          this.requestMap.set(turnRequestId, pending.returnTo || pending.from);
                          this.sendToCodex({
                              jsonrpc: "2.0",
                              id: turnRequestId,
                              method: "turn/start",
                              params: {
                                  threadId: this.currentThreadId,
                                  input: [{ type: "text", text: pending.text }]
                              }
                          });
                      }
                  } else if (parsed.error) {
                      // Handle thread/start error by informing all waiters and clearing queue
                      while (this.pendingPrompts.length > 0) {
                          const pending = this.pendingPrompts.shift()!;
                          if (this.hubWs && this.hubWs.readyState === WebSocket.OPEN) {
                              this.hubWs.send(JSON.stringify({
                                  id: randomUUID(),
                                  from: this.agentId,
                                  to: pending.returnTo || pending.from,
                                  eventType: 'rpc_response',
                                  timestamp: Date.now(),
                                  payload: { error: parsed.error }
                              }));
                          }
                      }
                  }
                  return; // Do not route the raw thread/start response back to any user
              }  
        // Determine routing destination
      let targetAgent = 'lead'; // fallback
      
      if (parsed.id !== undefined && this.requestMap.has(parsed.id)) {
          targetAgent = this.requestMap.get(parsed.id)!;
          this.requestMap.delete(parsed.id); // clean up
      }

      // Determine event type based on JSON-RPC structure
      let eventType = 'rpc_response';
      if (parsed.method && parsed.id === undefined) eventType = 'rpc_notification';
      if (parsed.method && parsed.id !== undefined) eventType = 'rpc_request'; // server-initiated request
      let payload: unknown = parsed;
      let returnTo: string | undefined;

      const delegations = extractSupportedDelegationsFromCodexPayload(parsed);
      if (delegations.length > 0) {
        for (const delegation of delegations) {
          if (!this.shouldForwardDelegation(delegation.to, delegation.task)) {
            continue;
          }
          const delegateHubMessage = {
            id: randomUUID(),
            from: this.agentId,
            to: delegation.to,
            eventType: 'delegate',
            returnTo: this.agentId,
            timestamp: Date.now(),
            payload: delegation.task
          };

          if (this.hubWs && this.hubWs.readyState === WebSocket.OPEN) {
            this.hubWs.send(JSON.stringify(delegateHubMessage));
          }
        }
        return;
      }

      const hubMsg = {
        id: randomUUID(),
        from: this.agentId,
        to: targetAgent, 
        eventType,
        returnTo,
        timestamp: Date.now(),
        payload
      };

      if (this.hubWs && this.hubWs.readyState === WebSocket.OPEN) {
        this.hubWs.send(JSON.stringify(hubMsg));
      }
    } catch (e) {
      console.error('[CodexAdapter] Error in handleCodexMessage:', e, line);
    }
  }

  private sendToCodex(payload: any) {
    if (this.codexProcess && this.codexProcess.stdin && !this.codexProcess.stdin.destroyed) {
      this.codexProcess.stdin.write(JSON.stringify(payload) + "\n");
    }
  }

  private shouldForwardDelegation(to: string, task: string): boolean {
    const now = Date.now();
    for (const [key, timestamp] of this.recentDelegationTimestamps.entries()) {
      if (now - timestamp > this.delegationDedupWindowMs) {
        this.recentDelegationTimestamps.delete(key);
      }
    }

    const dedupKey = `${to}\u0000${task}`;
    const previous = this.recentDelegationTimestamps.get(dedupKey);
    if (previous !== undefined && now - previous <= this.delegationDedupWindowMs) {
      return false;
    }

    this.recentDelegationTimestamps.set(dedupKey, now);
    return true;
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
