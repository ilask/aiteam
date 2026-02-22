import { describe, it, expect, beforeAll, afterAll } from 'vitest';
import { promises as fs } from 'fs';
import * as path from 'path';
import { setTimeout as sleep } from 'timers/promises';
import { spawn } from 'child_process';
import { WezTermSession, canRunWezTermE2E, getFreePort } from './wezterm-harness.js';

const describeWithWezTerm = canRunWezTermE2E() ? describe : describe.skip;
type PngFileMeta = { name: string; mtimeMs: number; size: number };

function getCodexOutputBlocks(screen: string): string {
  const matches = screen.match(/\[codex\][\s\S]*?(?=You\(codex\)>|$)/g);
  return (matches ?? []).join('\n');
}

function getLastStatusBlock(screen: string): string {
  const idx = screen.lastIndexOf('[status]');
  return idx >= 0 ? screen.slice(idx) : screen;
}

function parsePairCount(statusBlock: string, from: string, to: string): number {
  const compact = statusBlock.replace(/\s+/g, '');
  const match = compact.match(new RegExp(`${from}->${to}=(\\d+)`));
  if (!match) {
    return 0;
  }
  return Number.parseInt(match[1], 10);
}

function parseDelegateCount(statusBlock: string): number {
  const compact = statusBlock.replace(/\s+/g, '');
  const match = compact.match(/-routed\.delegate:(\d+)/);
  if (!match) {
    return 0;
  }
  return Number.parseInt(match[1], 10);
}

async function listPngFiles(outputDir: string): Promise<PngFileMeta[]> {
  try {
    const entries = await fs.readdir(outputDir);
    const pngNames = entries.filter((name) => name.toLowerCase().endsWith('.png')).sort();
    return await Promise.all(
      pngNames.map(async (name) => {
        const fullPath = path.join(outputDir, name);
        const stat = await fs.stat(fullPath);
        return {
          name,
          mtimeMs: stat.mtimeMs,
          size: stat.size
        };
      })
    );
  } catch (err) {
    const code = (err as NodeJS.ErrnoException).code;
    if (code === 'ENOENT') {
      return [];
    }
    throw err;
  }
}

async function readTailLines(filePath: string, maxLines: number): Promise<string> {
  try {
    const raw = await fs.readFile(filePath, 'utf8');
    const lines = raw
      .split(/\r?\n/)
      .map((line) => line.trim())
      .filter((line) => line.length > 0);
    return lines.slice(-maxLines).join('\n');
  } catch (err) {
    const code = (err as NodeJS.ErrnoException).code;
    if (code === 'ENOENT') {
      return '';
    }
    throw err;
  }
}

function extractJsonObjectFromText(text: string): string | null {
  const fenced = text.match(/```json\s*([\s\S]*?)```/i);
  if (fenced) {
    return fenced[1].trim();
  }

  const firstBrace = text.indexOf('{');
  const lastBrace = text.lastIndexOf('}');
  if (firstBrace >= 0 && lastBrace > firstBrace) {
    return text.slice(firstBrace, lastBrace + 1).trim();
  }
  return null;
}

async function runGeminiJudge(
  prompt: string,
  timeoutMs = 180000
): Promise<{ pass: boolean; score: number; raw: string; parsed: Record<string, unknown> }> {
  return new Promise((resolve, reject) => {
    const child = spawn(
      'gemini',
      ['-o', 'text'],
      {
      cwd: process.cwd(),
      env: process.env,
      stdio: ['pipe', 'pipe', 'pipe'],
      shell: process.platform === 'win32'
    });

    let stdout = '';
    let stderr = '';
    let settled = false;

    const timer = setTimeout(() => {
      if (settled) {
        return;
      }
      settled = true;
      child.kill();
      reject(new Error(`Gemini judge timed out after ${timeoutMs}ms`));
    }, timeoutMs);

    child.stdout.on('data', (chunk) => {
      stdout += chunk.toString();
    });
    child.stderr.on('data', (chunk) => {
      stderr += chunk.toString();
    });

    if (child.stdin) {
      child.stdin.write(`${prompt}\n`);
      child.stdin.end();
    }

    child.on('error', (err) => {
      if (settled) {
        return;
      }
      settled = true;
      clearTimeout(timer);
      reject(err);
    });

    child.on('close', (code) => {
      if (settled) {
        return;
      }
      settled = true;
      clearTimeout(timer);

      if (code !== 0) {
        reject(
          new Error(
            `Gemini judge exited with code ${code}\n[stdout]\n${stdout}\n[stderr]\n${stderr}`
          )
        );
        return;
      }

      const jsonCandidate = extractJsonObjectFromText(stdout);
      if (!jsonCandidate) {
        reject(
          new Error(
            `Gemini judge output did not include JSON.\n[stdout]\n${stdout}\n[stderr]\n${stderr}`
          )
        );
        return;
      }

      let parsed: Record<string, unknown>;
      try {
        parsed = JSON.parse(jsonCandidate) as Record<string, unknown>;
      } catch (err) {
        reject(
          new Error(
            `Failed to parse Gemini judge JSON: ${String(err)}\n[json]\n${jsonCandidate}\n[stdout]\n${stdout}`
          )
        );
        return;
      }

      const pass = parsed.pass === true;
      const score =
        typeof parsed.score === 'number'
          ? parsed.score
          : Number.parseFloat(String(parsed.score ?? Number.NaN));

      resolve({
        pass,
        score: Number.isFinite(score) ? score : 0,
        raw: stdout,
        parsed
      });
    });
  });
}

describeWithWezTerm('E2E: Inter-Agent Collaboration (WezTerm CLI, no mocks)', () => {
  let session: WezTermSession;

  beforeAll(async () => {
    session = new WezTermSession();
    const requestedPort = await getFreePort();
    await session.start('codex', requestedPort, 90000);
  }, 120000);

  afterAll(async () => {
    if (session) {
      await session.shutdownAndDispose();
    }
  }, 120000);

  it('reports codex/claude/gemini as connected in /status', async () => {
    await session.sendLine('/status');
    await session.waitForText('- codex: connected', 60000, 'Timeout waiting for codex connected');
    await session.waitForText('- claude: connected', 60000, 'Timeout waiting for claude connected');
    const screen = await session.waitForText(
      '- gemini: connected',
      60000,
      'Timeout waiting for gemini connected'
    );

    expect(screen).toContain('- codex: connected');
    expect(screen).toContain('- claude: connected');
    expect(screen).toContain('- gemini: connected');
  }, 120000);

  it('drives deep growi collaboration with communication evidence and new nanobanana diagram output', async () => {
    const outputDir = path.join(process.cwd(), 'nanobanana-output');
    const beforePngFiles = await listPngFiles(outputDir);
    const beforeByName = new Map(beforePngFiles.map((entry) => [entry.name, entry]));

    const scenarioToken = `growi_deep_${Date.now()}`;
    const collaborationPrompt = [
      'You are codex main coordinator.',
      'Hard constraint: do NOT run shell commands or terminal tools yourself.',
      'Focus only on agent-to-agent delegation and synthesis.',
      'Do NOT use internal collab tools like spawnAgent/wait/closeAgent.',
      'Only delegate using literal @claude and @gemini lines.',
      'Never ask claude to read/write files. Claude must answer in plain text only.',
      'Do not skip delegation. You MUST delegate to claude and gemini first.',
      'First output exactly two delegation lines (one per line) before any explanation:',
      '@claude Provide a plain-text GROWI semantic-search architecture overview (Elasticsearch vector backend + OpenAI embeddings). Do not use file/tools.',
      `@gemini /generate "GROWI semantic search architecture diagram ${scenarioToken}" --count=1`,
      'Then continue autonomous multi-agent workflow:',
      '1) delegate to claude for GROWI semantic search overview design',
      '(Elasticsearch vector backend + OpenAI embeddings).',
      `2) delegate to gemini with an actual /generate command that includes token ${scenarioToken}.`,
      '3) produce codex impact scope.',
      '4) perform mutual review among claude/codex/gemini and resolve disagreements.',
      'Return concise updates while work is running.',
      'Do not ask lead for extra steps unless blocked.'
    ].join(' ');

    await session.sendLine(collaborationPrompt);

    let communicationObserved = false;
    let statusBlock = '';
    let newPngFiles: string[] = [];
    const communicationDeadline = Date.now() + 300000;

    while (Date.now() < communicationDeadline) {
      await session.sendLine('/status');
      await sleep(900);
      const statusScreen = await session.getScreenText();
      statusBlock = getLastStatusBlock(statusScreen);

      const codexToClaude = parsePairCount(statusBlock, 'codex', 'claude');
      const codexToGemini = parsePairCount(statusBlock, 'codex', 'gemini');
      const delegateCount = parseDelegateCount(statusBlock);
      communicationObserved =
        codexToClaude > 0 &&
        codexToGemini > 0 &&
        delegateCount >= 2;

      const afterPngFiles = await listPngFiles(outputDir);
      newPngFiles = afterPngFiles
        .filter((entry) => {
          const before = beforeByName.get(entry.name);
          if (!before) {
            return true;
          }
          return entry.mtimeMs > before.mtimeMs + 1 || entry.size !== before.size;
        })
        .map((entry) => entry.name);

      if (communicationObserved && newPngFiles.length > 0) {
        break;
      }

      await sleep(2200);
    }

    expect(communicationObserved, `Communication evidence missing.\nLast status block:\n${statusBlock}`).toBe(true);
    expect(newPngFiles.length, `No new PNG generated.\nLast status block:\n${statusBlock}`).toBeGreaterThan(0);

    await session.sendLine(
      'Provide final consolidated overview with sections: CLAUDE_DESIGN, CODEX_IMPACT, GEMINI_DIAGRAM, MUTUAL_REVIEW.'
    );
    await sleep(12000);
    const screenAfterFinalizePrompt = await session.getScreenText();
    const codexOutput = getCodexOutputBlocks(screenAfterFinalizePrompt);

    const newestImageName = [...newPngFiles].sort().at(-1) ?? '';
    const newestImagePath = path.join(outputDir, newestImageName);
    const newestImageStat = await fs.stat(newestImagePath);
    expect(newestImageStat.size).toBeGreaterThan(0);

    const debugLogPath = session.getDebugLogPath();
    const debugLogTail = await readTailLines(debugLogPath, 200);
    const debugLogStat = await fs.stat(debugLogPath);
    expect(debugLogStat.size).toBeGreaterThan(0);
    const debugRouteTail = debugLogTail
      .split(/\r?\n/)
      .filter((line) => line.includes('"eventType":"message_routed"'))
      .slice(-24)
      .join('\n');

    const judgeInput = {
      objective:
        'Evaluate whether this run achieved deep multi-agent collaboration for GROWI semantic-search overview design: claude design, codex impact, gemini nanobanana diagram generation, and mutual review-based finalization.',
      requiredChecks: [
        'codex delegated to claude and gemini',
        'gemini path used nanobanana-style image generation and produced a new PNG',
        'final codex narrative references contributions from claude/codex/gemini',
        'conversation quality indicates non-trivial collaboration, not single-agent only'
      ],
      evidence: {
        statusBlock,
        newPngFiles,
        newestImageName,
        newestImageBytes: newestImageStat.size,
        codexOutputTail: codexOutput.slice(-4500),
        debugLogPath,
        debugRouteTail
      }
    };

    const judgePrompt = [
      'You are an E2E test judge.',
      'Decide pass/fail for the objective using the evidence JSON.',
      'Return strict JSON only with this schema:',
      '{"pass":boolean,"score":number,"checks":{"delegation":boolean,"image_generation":boolean,"multi_agent_synthesis":boolean,"quality":boolean},"reasons":[string],"missing":[string]}',
      'Scoring scale: 0.0 (fail) to 5.0 (excellent).',
      'If uncertain, be conservative and set pass=false.',
      '',
      JSON.stringify(judgeInput)
    ].join('\n');

    const judge = await runGeminiJudge(judgePrompt, 210000);
    expect(
      judge.pass,
      `LLM judge returned fail.\nScore=${judge.score}\nParsed=${JSON.stringify(judge.parsed, null, 2)}\nRaw=${judge.raw}`
    ).toBe(true);
    expect(judge.score).toBeGreaterThanOrEqual(3.0);
  }, 780000);
});
