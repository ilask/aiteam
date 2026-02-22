import { spawn, spawnSync } from 'child_process';
import * as fs from 'fs';
import * as net from 'net';
import * as path from 'path';
import { setTimeout as sleep } from 'timers/promises';

type ProcessResult = {
  code: number;
  stdout: string;
  stderr: string;
};

const DEFAULT_SCROLLBACK_LINES = 600;
const DEFAULT_POLL_INTERVAL_MS = 400;
const DEFAULT_WEZTERM_CLI_TIMEOUT_MS = 20000;
const TRANSIENT_ERROR_MARKERS = ['os error 10054', 'connection refused', 'broken pipe'];
const DEFAULT_E2E_DEBUG_LOG_DIR = path.join('tmp', 'e2e-debug');

function collectLines(text: string): string[] {
  return text
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter((line) => line.length > 0);
}

function formatFailure(args: string[], result: ProcessResult): string {
  return [
    `wezterm command failed (exit=${result.code})`,
    `cmd: ${args.join(' ')}`,
    `[stdout]`,
    result.stdout,
    `[stderr]`,
    result.stderr
  ].join('\n');
}

function isTransientCliError(result: ProcessResult): boolean {
  const combined = `${result.stdout}\n${result.stderr}`.toLowerCase();
  return TRANSIENT_ERROR_MARKERS.some((marker) => combined.includes(marker));
}

function parsePaneId(stdout: string, stderr: string): number {
  const lines = [...collectLines(stdout), ...collectLines(stderr)];
  const numericLines = lines.filter((line) => /^\d+$/.test(line));
  if (numericLines.length === 0) {
    throw new Error(`Failed to parse pane id from wezterm output.\nstdout:\n${stdout}\nstderr:\n${stderr}`);
  }
  return Number.parseInt(numericLines[numericLines.length - 1], 10);
}

async function runCommand(
  executable: string,
  args: string[],
  cwd: string,
  timeoutMs = DEFAULT_WEZTERM_CLI_TIMEOUT_MS
): Promise<ProcessResult> {
  return new Promise<ProcessResult>((resolve, reject) => {
    const child = spawn(executable, args, {
      cwd,
      env: process.env,
      stdio: ['ignore', 'pipe', 'pipe'],
      windowsHide: true
    });

    let stdout = '';
    let stderr = '';
    let didTimeout = false;
    const timeoutHandle = setTimeout(() => {
      didTimeout = true;
      try {
        child.kill();
      } catch {
        // Ignore kill failures.
      }
    }, timeoutMs);

    child.stdout.on('data', (chunk) => {
      stdout += chunk.toString();
    });
    child.stderr.on('data', (chunk) => {
      stderr += chunk.toString();
    });

    child.on('error', (error) => {
      clearTimeout(timeoutHandle);
      reject(error);
    });
    child.on('close', (code) => {
      clearTimeout(timeoutHandle);
      if (didTimeout) {
        resolve({
          code: -1,
          stdout,
          stderr: `${stderr}\nwezterm command timed out after ${timeoutMs}ms`
        });
        return;
      }
      resolve({ code: code ?? -1, stdout, stderr });
    });
  });
}

export function resolveWezTermExecutable(): string | null {
  const envPath = process.env.AITEAM_WEZTERM_EXE;
  if (envPath && fs.existsSync(envPath)) {
    return envPath;
  }

  if (process.platform !== 'win32') {
    return null;
  }

  const defaultPath = 'C:\\Program Files\\WezTerm\\wezterm.exe';
  if (fs.existsSync(defaultPath)) {
    return defaultPath;
  }

  const whereResult = spawnSync('where.exe', ['wezterm.exe'], {
    encoding: 'utf8',
    windowsHide: true
  });

  if (whereResult.status !== 0 || !whereResult.stdout) {
    return null;
  }

  const firstLine = collectLines(whereResult.stdout)[0];
  return firstLine ? firstLine : null;
}

export function canRunWezTermE2E(): boolean {
  const resolved = resolveWezTermExecutable();
  if (!resolved) {
    return false;
  }
  if (process.platform !== 'win32') {
    return false;
  }

  const probe = spawnSync(resolved, ['cli', '--prefer-mux', 'list', '--format', 'json'], {
    encoding: 'utf8',
    windowsHide: true
  });

  return probe.status === 0;
}

export async function getFreePort(): Promise<number> {
  return new Promise<number>((resolve, reject) => {
    const server = net.createServer();
    server.unref();
    server.on('error', reject);
    server.listen(0, '127.0.0.1', () => {
      const address = server.address();
      if (!address || typeof address === 'string') {
        server.close(() => reject(new Error('Failed to allocate a test port.')));
        return;
      }
      const selectedPort = address.port;
      server.close((closeErr) => {
        if (closeErr) {
          reject(closeErr);
          return;
        }
        resolve(selectedPort);
      });
    });
  });
}

export class WezTermSession {
  private readonly cwd: string;
  private readonly weztermExe: string;
  private readonly workspace: string;
  private readonly debugLogPath: string;
  private readonly scrollbackLines: number;
  private readonly pollIntervalMs: number;
  private paneId: number | null = null;
  private mainAgent: string = 'codex';
  private hubPort: number | null = null;

  constructor(options?: {
    cwd?: string;
    weztermExe?: string;
    scrollbackLines?: number;
    pollIntervalMs?: number;
  }) {
    const resolved = options?.weztermExe ?? resolveWezTermExecutable();
    if (!resolved) {
      throw new Error(
        'wezterm executable was not found. Install WezTerm or set AITEAM_WEZTERM_EXE.'
      );
    }

    this.weztermExe = resolved;
    this.cwd = options?.cwd ?? process.cwd();
    this.workspace = `aiteam-e2e-${Date.now()}-${Math.random().toString(16).slice(2, 8)}`;
    this.debugLogPath = path.resolve(this.cwd, DEFAULT_E2E_DEBUG_LOG_DIR, `${this.workspace}.ndjson`);
    this.scrollbackLines = options?.scrollbackLines ?? DEFAULT_SCROLLBACK_LINES;
    this.pollIntervalMs = options?.pollIntervalMs ?? DEFAULT_POLL_INTERVAL_MS;
  }

  public getHubPort(): number {
    if (this.hubPort === null) {
      throw new Error('Hub port is not available before session start.');
    }
    return this.hubPort;
  }

  public getDebugLogPath(): string {
    return this.debugLogPath;
  }

  public async start(mainAgent: string, requestedPort: number, startupTimeoutMs: number): Promise<number> {
    this.mainAgent = mainAgent;
    this.paneId = await this.spawnPane();
    fs.mkdirSync(path.dirname(this.debugLogPath), { recursive: true });

    await this.sendLine(`set PORT=${requestedPort}`);
    await this.sendLine('set NO_COLOR=1');
    await this.sendLine('set AITEAM_CLAUDE_TEXT_ONLY=1');
    await this.sendLine(`set "AITEAM_DEBUG_LOG_FILE=${this.debugLogPath}"`);
    await this.sendLine(`node dist\\cli.js ${mainAgent}`);

    const startupScreen = await this.waitForText(
      '--- aiteam CLI ---',
      startupTimeoutMs,
      'Timeout waiting for CLI startup banner'
    );

    const fallbackMatch = startupScreen.match(/\[aiteam\] Port \d+ is in use\. Using port (\d+)\./);
    this.hubPort = fallbackMatch ? Number.parseInt(fallbackMatch[1], 10) : requestedPort;
    return this.hubPort;
  }

  public async sendLine(text: string): Promise<void> {
    const paneId = this.requirePaneId();
    await this.runCliCommand([
      'cli',
      '--prefer-mux',
      'send-text',
      '--pane-id',
      String(paneId),
      '--no-paste',
      `${text}\r`
    ]);
  }

  public async getScreenText(): Promise<string> {
    const paneId = this.requirePaneId();
    const result = await this.runCliCommand([
      'cli',
      '--prefer-mux',
      'get-text',
      '--pane-id',
      String(paneId),
      '--start-line',
      `-${this.scrollbackLines}`
    ]);
    return result.stdout;
  }

  public async waitForText(needle: string, timeoutMs: number, timeoutLabel: string): Promise<string> {
    const deadline = Date.now() + timeoutMs;
    let latest = '';
    while (Date.now() < deadline) {
      latest = await this.getScreenText();
      if (latest.includes(needle)) {
        return latest;
      }
      await sleep(this.pollIntervalMs);
    }
    const tail = latest.slice(-1400);
    throw new Error(`${timeoutLabel}\nNeedle: ${needle}\nLast screen tail:\n${tail}`);
  }

  public async waitForRegex(regex: RegExp, timeoutMs: number, timeoutLabel: string): Promise<string> {
    const deadline = Date.now() + timeoutMs;
    let latest = '';
    while (Date.now() < deadline) {
      latest = await this.getScreenText();
      if (regex.test(latest)) {
        return latest;
      }
      await sleep(this.pollIntervalMs);
    }
    const tail = latest.slice(-1400);
    throw new Error(`${timeoutLabel}\nPattern: ${regex}\nLast screen tail:\n${tail}`);
  }

  public async shutdownAndDispose(): Promise<void> {
    if (this.paneId === null) {
      return;
    }
    try {
      await this.sendLine('exit');
      await this.waitForText('Shutting down', 30000, `Timeout waiting for ${this.mainAgent} shutdown`);
    } catch {
      // Ignore and continue to kill-pane cleanup.
    } finally {
      await this.killPane();
      this.paneId = null;
    }
  }

  public async killPaneImmediately(): Promise<void> {
    if (this.paneId === null) {
      return;
    }
    await this.killPane();
    this.paneId = null;
  }

  private requirePaneId(): number {
    if (this.paneId === null) {
      throw new Error('WezTerm pane is not initialized.');
    }
    return this.paneId;
  }

  private async spawnPane(): Promise<number> {
    const result = await this.runCliCommand([
      'cli',
      '--prefer-mux',
      'spawn',
      '--new-window',
      '--workspace',
      this.workspace,
      '--cwd',
      path.resolve(this.cwd),
      '--',
      'cmd',
      '/k'
    ]);
    return parsePaneId(result.stdout, result.stderr);
  }

  private async killPane(): Promise<void> {
    const paneId = this.requirePaneId();
    try {
      await this.runCliCommand(
        ['cli', '--prefer-mux', 'kill-pane', '--pane-id', String(paneId)],
        { retries: 0 }
      );
    } catch {
      // Ignore cleanup failures to preserve original test failures.
    }
  }

  private async runCliCommand(args: string[], options?: { retries?: number }): Promise<ProcessResult> {
    const retries = options?.retries ?? 2;
    let attempt = 0;
    let lastFailure: ProcessResult | null = null;
    while (attempt <= retries) {
      const result = await runCommand(this.weztermExe, args, this.cwd);
      if (result.code === 0) {
        return result;
      }
      lastFailure = result;
      const canRetry = attempt < retries && isTransientCliError(result);
      if (!canRetry) {
        break;
      }
      attempt += 1;
      await sleep(300 * attempt);
    }

    throw new Error(formatFailure(args, lastFailure ?? { code: -1, stdout: '', stderr: '' }));
  }
}
