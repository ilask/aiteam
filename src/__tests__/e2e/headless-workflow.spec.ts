import { describe, it, expect, beforeAll, afterAll } from 'vitest';
import { spawn, ChildProcess } from 'child_process';
import * as path from 'path';
import * as url from 'url';

const __dirname = url.fileURLToPath(new URL('.', import.meta.url));
const CLI_PATH = path.resolve(__dirname, '../../../dist/cli.js');

describe('E2E: Headless Architecture Workflow', () => {
  let cliProcess: ChildProcess;
  let outputBuffer = '';

  beforeAll(async () => {
    // Start the CLI process
    cliProcess = spawn('node', [CLI_PATH], {
      env: { ...process.env, PORT: '4510' },
      stdio: ['pipe', 'pipe', 'pipe']
    });

    if (!cliProcess.stdout || !cliProcess.stderr || !cliProcess.stdin) {
      throw new Error('Failed to attach to CLI stdio');
    }

    cliProcess.stdout.on('data', (data) => {
      outputBuffer += data.toString();
    });

    cliProcess.stderr.on('data', (data) => {
      // Optional: log or track stderr
      outputBuffer += data.toString();
    });

    // Wait for the CLI to be fully ready
    await new Promise<void>((resolve, reject) => {
      const timeout = setTimeout(() => reject(new Error('Timeout waiting for CLI ready')), 15000);
      const interval = setInterval(() => {
        if (outputBuffer.includes('Main agent: codex (default: codex)')) {
          clearTimeout(timeout);
          clearInterval(interval);
          resolve();
        }
      }, 500);
    });
  }, 60000);

  afterAll(() => {
    if (cliProcess) {
      cliProcess.kill();
    }
  });

  it('should route message to codex and receive a response', async () => {
    // Clear buffer before test
    outputBuffer = '';

    // Ensure codex is connected before first prompt to reduce startup flakiness.
    cliProcess.stdin!.write('/status' + String.fromCharCode(10));
    await new Promise<void>((resolve, reject) => {
      const timeout = setTimeout(
        () => reject(new Error('Timeout waiting for codex connected status')),
        20000
      );
      const interval = setInterval(() => {
        if (outputBuffer.includes('- codex: connected')) {
          clearTimeout(timeout);
          clearInterval(interval);
          resolve();
        }
      }, 500);
    });
    
    // Send a prompt to codex
    cliProcess.stdin!.write('Hello, are you there?' + String.fromCharCode(10));

    // Wait for codex response
    await new Promise<void>((resolve, reject) => {
      const timeout = setTimeout(() => reject(new Error('Timeout waiting for Codex response')), 45000);
      const interval = setInterval(() => {
        // We look for [codex] in the output indicating a response
        if (outputBuffer.includes('[codex]')) {
          clearTimeout(timeout);
          clearInterval(interval);
          resolve();
        }
      }, 500);
    });

    expect(outputBuffer).toContain('[codex]');
  }, 60000);

  it('should shutdown cleanly on exit command', async () => {
    cliProcess.stdin!.write('exit' + String.fromCharCode(10));

    await new Promise<void>((resolve, reject) => {
      const timeout = setTimeout(() => reject(new Error('Timeout waiting for exit')), 10000);
      cliProcess.on('exit', () => {
        clearTimeout(timeout);
        resolve();
      });
    });

    expect(cliProcess.killed || cliProcess.exitCode === 0 || cliProcess.exitCode === null).toBe(true);
  }, 15000);
});
