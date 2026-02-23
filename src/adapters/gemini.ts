import { spawn, ChildProcess } from 'child_process';
import * as readline from 'readline';
import { WebSocket } from 'ws';
import { randomUUID } from 'crypto';
import * as fs from 'fs';
import * as path from 'path';

type ExistsSyncFn = (path: string) => boolean;
type ReadFileSyncFn = (path: string) => string;
const AUTONOMOUS_MODE_DISABLED_VALUES = new Set(['0', 'false', 'off', 'no']);
const DEFAULT_GEMINI_GENERATE_MAX_ATTEMPTS = 3;
const DEFAULT_GEMINI_PROCESS_TIMEOUT_MS = 180000;

export function isGeminiAutonomousModeEnabled(rawValue: string | undefined): boolean {
  if (!rawValue) return true;
  return !AUTONOMOUS_MODE_DISABLED_VALUES.has(rawValue.trim().toLowerCase());
}

export function buildGeminiAutonomousPrompt(agentId: string, originalPrompt: string): string {
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

export function extractGeminiDelegationFromText(textContent: string): {
  to: string;
  task: string;
} | null {
  const match = textContent.match(/^@(\w+)\s+([\s\S]*)$/);
  if (!match) {
    return null;
  }
  const task = match[2].trim();
  if (!task) {
    return null;
  }
  return {
    to: match[1],
    task
  };
}

function stripGeminiApiKeyPrefix(value: string): string {
  return value.startsWith('GEMINI_API_KEY=')
    ? value.slice('GEMINI_API_KEY='.length)
    : value;
}

function trimOuterQuotes(value: string): string {
  if (
    (value.startsWith('"') && value.endsWith('"')) ||
    (value.startsWith("'") && value.endsWith("'"))
  ) {
    return value.slice(1, -1).trim();
  }
  return value;
}

export function normalizeGeminiApiKey(rawValue: string): string {
  let value = rawValue.trim();
  value = stripGeminiApiKeyPrefix(value);
  value = trimOuterQuotes(value);
  return value.trim();
}

export function resolveGeminiApiKeyFromEnv(
  env: NodeJS.ProcessEnv,
  deps?: {
    existsSync?: ExistsSyncFn;
    readFileSync?: ReadFileSyncFn;
  }
): string | undefined {
  const existsSync = deps?.existsSync ?? fs.existsSync;
  const readFileSync =
    deps?.readFileSync ??
    ((path: string) => fs.readFileSync(path, { encoding: 'utf8' }));

  const readKeyFromPath = (pathCandidate: string): string | undefined => {
    const trimmedPath = pathCandidate.trim();
    if (!trimmedPath || !existsSync(trimmedPath)) {
      return undefined;
    }
    const fileContent = readFileSync(trimmedPath);
    const normalized = normalizeGeminiApiKey(fileContent);
    return normalized.length > 0 ? normalized : undefined;
  };

  const fileEnv = env.GEMINI_API_KEY_FILE ?? '';
  const normalizedFileEnv = normalizeGeminiApiKey(fileEnv);
  const keyFromExplicitFile =
    readKeyFromPath(fileEnv) ?? readKeyFromPath(normalizedFileEnv);
  if (keyFromExplicitFile) {
    return keyFromExplicitFile;
  }

  const keyEnv = env.GEMINI_API_KEY ?? '';
  const normalizedKeyEnv = normalizeGeminiApiKey(keyEnv);
  const keyFromPathValue =
    readKeyFromPath(keyEnv) ?? readKeyFromPath(normalizedKeyEnv);
  if (keyFromPathValue) {
    return keyFromPathValue;
  }

  return normalizedKeyEnv.length > 0 ? normalizedKeyEnv : undefined;
}

export function buildGeminiPromptArgs(
  promptText: string,
  resumeSessionId?: string | null,
  approvalMode?: string | null
): string[] {
  const resolvedApprovalMode =
    approvalMode?.trim() ||
    process.env.AITEAM_GEMINI_APPROVAL_MODE?.trim() ||
    'yolo';
  const args = ['-o', 'stream-json'];
  if (resolvedApprovalMode.length > 0) {
    args.push('--approval-mode', resolvedApprovalMode);
  }
  if (resumeSessionId && resumeSessionId.trim().length > 0) {
    args.push('--resume', resumeSessionId.trim());
  }
  args.push('-p', promptText);
  return args;
}

function buildGeminiTextPromptArgs(
  promptText: string,
  resumeSessionId?: string | null,
  approvalMode?: string | null
): string[] {
  const resolvedApprovalMode =
    approvalMode?.trim() ||
    process.env.AITEAM_GEMINI_APPROVAL_MODE?.trim() ||
    'yolo';
  const args = ['-o', 'text'];
  if (resolvedApprovalMode.length > 0) {
    args.push('--approval-mode', resolvedApprovalMode);
  }
  if (resumeSessionId && resumeSessionId.trim().length > 0) {
    args.push('--resume', resumeSessionId.trim());
  }
  args.push('-p', promptText);
  return args;
}

function isGeminiGeneratePrompt(promptText: string): boolean {
  return /^\/generate(\s|$)/.test(promptText.trimStart());
}

function parsePositiveInt(rawValue: string | undefined, fallbackValue: number): number {
  const parsed = Number.parseInt(rawValue?.trim() ?? '', 10);
  if (!Number.isFinite(parsed) || parsed < 1) {
    return fallbackValue;
  }
  return parsed;
}

function extractPrimaryGenerateCommand(promptText: string): string {
  const match = promptText.match(/^\s*\/generate[^\r\n]*/m);
  if (!match) {
    return promptText.trim();
  }
  return match[0].trim();
}

type GeminiGenerateRequest = {
  originalCommand: string;
  prompt: string;
  count: number;
};

function parseGenerateRequest(command: string): GeminiGenerateRequest | null {
  const trimmed = command.trim();
  const match = trimmed.match(/^\/generate\s+(.+?)(?:\s+--count(?:=|\s)(\d+))?\s*$/i);
  if (!match) {
    return null;
  }

  let promptPart = match[1].trim();
  if (
    (promptPart.startsWith('"') && promptPart.endsWith('"')) ||
    (promptPart.startsWith("'") && promptPart.endsWith("'"))
  ) {
    promptPart = promptPart.slice(1, -1).trim();
  }
  if (!promptPart) {
    return null;
  }

  const parsedCount = Number.parseInt(match[2] ?? '1', 10);
  const count = Number.isFinite(parsedCount) && parsedCount >= 1 ? parsedCount : 1;
  return {
    originalCommand: trimmed,
    prompt: promptPart,
    count
  };
}

function buildGenerateExecutionPrompt(request: GeminiGenerateRequest): string {
  return [
    'Use the nanobanana image-generation extension.',
    `Generate exactly ${request.count} PNG image(s) for this visual prompt:`,
    request.prompt,
    'Save the image(s) to the default workspace output directory.',
    'Return only absolute saved file path(s), one path per line.',
    `Requested command: ${request.originalCommand}`
  ].join('\n');
}

function hasImageOutputEvidence(text: string): boolean {
  return /[^\s"'`]+\.(png|jpg|jpeg|webp)\b/i.test(text);
}

function shouldRetryGenerateResult(
  output: string,
  stderr: string,
  exitCode: number | null
): boolean {
  if (exitCode !== 0) {
    return true;
  }
  const combined = `${output}\n${stderr}`.toLowerCase();
  if (combined.includes('no image data found')) {
    return true;
  }
  return !hasImageOutputEvidence(output);
}

function resolveGeminiCliEntrypoint(): string | null {
  if (process.platform !== 'win32') {
    return null;
  }
  const appData = process.env.APPDATA;
  if (!appData) {
    return null;
  }
  const candidate = path.join(
    appData,
    'npm',
    'node_modules',
    '@google',
    'gemini-cli',
    'dist',
    'index.js'
  );
  return fs.existsSync(candidate) ? candidate : null;
}

export class GeminiAdapter {
  private hubWs: WebSocket | null = null;
  private agentId: string;
  private hubUrl: string;
  private isStopping: boolean = false;
  private activeGeminiProcesses: Set<ChildProcess> = new Set();
  private resolvedGeminiApiKey: string | undefined;
  private geminiSessionId: string | null = null;
  private queuedPrompts: Array<{ promptText: string; returnTo: string }> = [];
  private isQueueProcessing = false;
  private autonomousModeEnabled: boolean;
  private readonly generateMaxAttempts: number;
  private readonly processTimeoutMs: number;

  constructor(hubUrl: string, agentId: string = 'gemini') {
    this.hubUrl = hubUrl;
    this.agentId = agentId;
    this.autonomousModeEnabled = isGeminiAutonomousModeEnabled(
      process.env.AITEAM_AUTONOMOUS_MODE
    );
    this.generateMaxAttempts = parsePositiveInt(
      process.env.AITEAM_GEMINI_GENERATE_MAX_ATTEMPTS,
      DEFAULT_GEMINI_GENERATE_MAX_ATTEMPTS
    );
    this.processTimeoutMs = parsePositiveInt(
      process.env.AITEAM_GEMINI_PROCESS_TIMEOUT_MS,
      DEFAULT_GEMINI_PROCESS_TIMEOUT_MS
    );
  }

  public async start() {
    return new Promise<void>((resolve, reject) => {
      this.hubWs = new WebSocket(this.hubUrl);

      this.hubWs.on('open', () => {
        // console.debug(`[GeminiAdapter] Connected to Hub at ${this.hubUrl}`);
        this.hubWs?.send(JSON.stringify({ type: 'identify', id: this.agentId }));
        this.resolvedGeminiApiKey = resolveGeminiApiKeyFromEnv(process.env);

        if (
          !this.resolvedGeminiApiKey &&
          !process.env.GOOGLE_GENAI_USE_VERTEXAI &&
          !process.env.GOOGLE_GENAI_USE_GCA
        ) {
          console.warn(
            '[GeminiAdapter] GEMINI_API_KEY is not set. Gemini authentication may fail.'
          );
        }

        resolve();
      });

      this.hubWs.on('message', (data) => {
        this.handleHubMessage(data.toString());
      });

      this.hubWs.on('error', (err) => {
        console.error(`[GeminiAdapter] Hub WS error:`, err);
        if (!this.isStopping) reject(err);
      });

      this.hubWs.on('close', () => {
        // console.debug(`[GeminiAdapter] Hub WS closed`);
        this.stop();
      });
    });
  }

  private getChildEnv(): NodeJS.ProcessEnv {
    if (!this.resolvedGeminiApiKey) {
      return process.env;
    }
    return {
      ...process.env,
      GEMINI_API_KEY: this.resolvedGeminiApiKey
    };
  }

  private enqueueGeminiPrompt(promptText: string, returnTo: string) {
    this.queuedPrompts.push({ promptText, returnTo });
    void this.processQueuedPrompts();
  }

  private async processQueuedPrompts() {
    if (this.isQueueProcessing || this.isStopping) {
      return;
    }

    this.isQueueProcessing = true;
    while (!this.isStopping && this.queuedPrompts.length > 0) {
      const nextPrompt = this.queuedPrompts.shift();
      if (!nextPrompt) {
        continue;
      }
      await this.runGeminiPrompt(nextPrompt.promptText, nextPrompt.returnTo);
    }
    this.isQueueProcessing = false;
  }

  private runGeminiPrompt(
    promptText: string,
    returnTo: string,
    attemptNumber = 1
  ): Promise<void> {
    return new Promise((resolve) => {
      const generateMode = isGeminiGeneratePrompt(promptText);
      const generateCommand = generateMode ? extractPrimaryGenerateCommand(promptText) : '';
      const generateRequest = generateMode ? parseGenerateRequest(generateCommand) : null;
      const promptToSend = generateMode
        ? generateRequest
          ? buildGenerateExecutionPrompt(generateRequest)
          : generateCommand
        : promptText;
      const args = generateMode
        ? buildGeminiTextPromptArgs(promptToSend, this.geminiSessionId)
        : buildGeminiPromptArgs(promptToSend, this.geminiSessionId);
      const geminiCliEntrypoint = resolveGeminiCliEntrypoint();
      const command = geminiCliEntrypoint ? process.execPath : 'gemini';
      const spawnArgs = geminiCliEntrypoint ? [geminiCliEntrypoint, ...args] : args;
      const useShell = process.platform === 'win32' && !geminiCliEntrypoint;
      let geminiProcess: ChildProcess;
      try {
        geminiProcess = spawn(command, spawnArgs, {
          stdio: ['ignore', 'pipe', 'pipe'],
          shell: useShell,
          env: this.getChildEnv()
        });
      } catch (err) {
        this.sendHubMessage(returnTo, 'gemini_error', {
          error: 'Failed to spawn Gemini process',
          details: String(err)
        });
        resolve();
        return;
      }

      this.activeGeminiProcesses.add(geminiProcess);
      let didTimeout = false;
      const timeoutHandle = setTimeout(() => {
        didTimeout = true;
        try {
          geminiProcess.kill();
        } catch {
          // Ignore timeout kill failures.
        }
      }, this.processTimeoutMs);

      const stdoutRl =
        !generateMode && geminiProcess.stdout
          ? readline.createInterface({ input: geminiProcess.stdout, terminal: false })
          : null;
      const stderrRl = geminiProcess.stderr
        ? readline.createInterface({ input: geminiProcess.stderr, terminal: false })
        : null;

      let bufferedStdout = '';
      let bufferedStderr = '';
      if (generateMode) {
        geminiProcess.stdout?.on('data', (chunk) => {
          bufferedStdout += chunk.toString();
        });
      } else {
        stdoutRl?.on('line', (line) => {
          this.handleGeminiMessage(line, returnTo);
        });
      }

      stderrRl?.on('line', (line) => {
        bufferedStderr += `${line}\n`;
        if (line.trim().length > 0) {
          console.error('[GeminiAdapter] Gemini stderr:', line);
        }
      });

      geminiProcess.on('error', (err) => {
        clearTimeout(timeoutHandle);
        console.error('[GeminiAdapter] Failed to spawn Gemini:', err);
        this.sendHubMessage(returnTo, 'gemini_error', {
          error: 'Failed to start Gemini process',
          details: String(err)
        });
      });

      geminiProcess.on('exit', (code) => {
        clearTimeout(timeoutHandle);
        const trimmedOutput = bufferedStdout.trim();
        if (generateMode) {
          const shouldRetry =
            attemptNumber < this.generateMaxAttempts &&
            shouldRetryGenerateResult(trimmedOutput, bufferedStderr, code);
          if (shouldRetry) {
            console.warn(
              `[GeminiAdapter] Generate attempt ${attemptNumber} did not produce image output. Retrying (${attemptNumber + 1}/${this.generateMaxAttempts}).`
            );
            stdoutRl?.close();
            stderrRl?.close();
            this.activeGeminiProcesses.delete(geminiProcess);
            void this.runGeminiPrompt(promptText, returnTo, attemptNumber + 1).then(resolve);
            return;
          }

          if (trimmedOutput.length > 0) {
            this.sendHubMessage(returnTo, 'gemini_text', trimmedOutput);
          }

          if (!hasImageOutputEvidence(trimmedOutput)) {
            this.sendHubMessage(returnTo, 'gemini_error', {
              error: 'Gemini generate output missing image evidence',
              attempt: attemptNumber,
              maxAttempts: this.generateMaxAttempts,
              exitCode: code,
              timedOut: didTimeout,
              stdout: trimmedOutput.slice(-4000),
              stderr: bufferedStderr.trim().slice(-2000)
            });
          }
        }
        if (code !== 0) {
          this.sendHubMessage(returnTo, 'gemini_error', {
            error: 'Gemini process exited with non-zero status',
            attempt: attemptNumber,
            exitCode: code,
            timedOut: didTimeout,
            stderr: bufferedStderr.trim().slice(-4000)
          });
        }
        stdoutRl?.close();
        stderrRl?.close();
        this.activeGeminiProcesses.delete(geminiProcess);
        resolve();
      });
    });
  }

  private handleHubMessage(data: string) {
    try {
      const msg = JSON.parse(data);
      if (
        (msg.eventType === 'prompt' ||
          msg.eventType === 'delegate' ||
          msg.eventType === 'raw') &&
        msg.payload !== undefined
      ) {
        const promptText =
          typeof msg.payload === 'string' ? msg.payload : JSON.stringify(msg.payload);
        if (!promptText || promptText.trim().length === 0) {
          return;
        }
        const effectivePromptText =
          this.autonomousModeEnabled && msg.from === 'lead'
            ? buildGeminiAutonomousPrompt(this.agentId, promptText)
            : promptText;

        const returnTo =
          typeof msg.returnTo === 'string'
            ? msg.returnTo
            : typeof msg.from === 'string'
              ? msg.from
              : 'lead';
        this.enqueueGeminiPrompt(effectivePromptText, returnTo);
      }
    } catch (e) {
      console.error('[GeminiAdapter] Failed to parse hub message:', e);
    }
  }

  private handleGeminiMessage(line: string, defaultTarget: string) {
    try {
      const parsed = JSON.parse(line);
      if (parsed.type === 'init' && typeof parsed.session_id === 'string') {
        this.geminiSessionId = parsed.session_id;
        return;
      }
      if (parsed.type === 'message' && parsed.role !== 'assistant') {
        return;
      }
      if (parsed.type === 'result' && parsed.status === 'success') {
        return;
      }

      // Attempt to extract text to check for delegation
      let textContent = '';
      if (parsed.message && parsed.message.content) {
          const content = parsed.message.content;
          textContent = typeof content === 'string' ? content : (Array.isArray(content) ? content.map((c:any) => c.text).join('') : JSON.stringify(content));
      } else if (parsed.result) {
          textContent = typeof parsed.result === 'string' ? parsed.result : JSON.stringify(parsed.result);
      }

      let to = defaultTarget;
      let eventType = parsed.type || 'gemini_event';
      let payload = parsed;

      // Check if this is an explicit delegation
      const delegation = extractGeminiDelegationFromText(textContent);
      if (delegation) {
          to = delegation.to;
          eventType = 'delegate';
          payload = delegation.task;
          // console.debug(`[GeminiAdapter] Intercepted delegation to ${to}`);
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

  private sendHubMessage(to: string, eventType: string, payload: unknown) {
    if (this.hubWs && this.hubWs.readyState === WebSocket.OPEN) {
      this.hubWs.send(
        JSON.stringify({
          id: randomUUID(),
          from: this.agentId,
          to,
          eventType,
          returnTo: this.agentId,
          timestamp: Date.now(),
          payload
        })
      );
    }
  }

  public stop() {
    if (this.isStopping) return;
    this.isStopping = true;

    this.queuedPrompts = [];
    for (const activeProcess of this.activeGeminiProcesses) {
      activeProcess.kill();
    }
    this.activeGeminiProcesses.clear();
    if (this.hubWs) {
        this.hubWs.close();
        this.hubWs = null;
    }
  }
}
