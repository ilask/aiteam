import { describe, it, expect } from 'vitest';
import { extractConversationalText, formatCliMessage } from '../cli.js';

describe('CLI output filter', () => {
  it('prints conversational assistant content', () => {
    const formatted = formatCliMessage({
      from: 'claude',
      payload: {
        type: 'assistant',
        message: {
          content: [{ type: 'text', text: 'Hello from Claude.' }]
        }
      }
    });

    expect(formatted).toEqual({
      from: 'claude',
      text: 'Hello from Claude.'
    });
  });

  it('ignores codex status notifications like turn/started', () => {
    const formatted = formatCliMessage({
      from: 'codex',
      payload: {
        jsonrpc: '2.0',
        method: 'turn/started',
        params: {
          turn: { id: 'turn_123', status: 'started' }
        }
      }
    });

    expect(formatted).toBeNull();
  });

  it('ignores codex token_count notifications', () => {
    const formatted = formatCliMessage({
      from: 'codex',
      payload: {
        jsonrpc: '2.0',
        method: 'token_count',
        params: {
          input_tokens: 10,
          output_tokens: 20
        }
      }
    });

    expect(formatted).toBeNull();
  });

  it('ignores codex thread/started notifications', () => {
    const formatted = formatCliMessage({
      from: 'codex',
      payload: {
        jsonrpc: '2.0',
        method: 'thread/started',
        params: {
          thread: { id: 'thread_123' }
        }
      }
    });

    expect(formatted).toBeNull();
  });

  it('extracts assistant text from codex turn output', () => {
    const text = extractConversationalText({
      jsonrpc: '2.0',
      method: 'turn/completed',
      params: {
        turn: {
          output: [
            {
              type: 'message',
              role: 'assistant',
              content: [{ type: 'output_text', text: 'Codex final answer.' }]
            }
          ]
        }
      }
    });

    expect(text).toBe('Codex final answer.');
  });

  it('extracts codex/event agent_message text', () => {
    const formatted = formatCliMessage({
      from: 'codex',
      payload: {
        jsonrpc: '2.0',
        method: 'codex/event/agent_message',
        params: {
          id: 'turn_123',
          msg: {
            type: 'agent_message',
            message: 'HELLO from codex/event'
          }
        }
      }
    });

    expect(formatted).toEqual({
      from: 'codex',
      text: 'HELLO from codex/event'
    });
  });

  it('extracts assistant text from item/completed notification', () => {
    const formatted = formatCliMessage({
      from: 'codex',
      payload: {
        jsonrpc: '2.0',
        method: 'item/completed',
        params: {
          threadId: 'thread_123',
          turnId: 'turn_123',
          item: {
            type: 'agentMessage',
            id: 'msg_123',
            text: 'HELLO from item/completed'
          }
        }
      }
    });

    expect(formatted).toEqual({
      from: 'codex',
      text: 'HELLO from item/completed'
    });
  });

  it('ignores codex/event warning notifications', () => {
    const formatted = formatCliMessage({
      from: 'codex',
      payload: {
        jsonrpc: '2.0',
        method: 'codex/event/warning',
        params: {
          msg: {
            type: 'warning',
            message: 'This is not conversational output.'
          }
        }
      }
    });

    expect(formatted).toBeNull();
  });

  it('prints structured adapter errors as conversational text', () => {
    const formatted = formatCliMessage({
      from: 'gemini',
      payload: {
        error: 'Gemini CLI failed to attach console',
        exitCode: 1,
        timedOut: false
      }
    });

    expect(formatted).toEqual({
      from: 'gemini',
      text: 'Gemini CLI failed to attach console (exit=1)'
    });
  });

  it('prints hub delivery errors as conversational text', () => {
    const formatted = formatCliMessage({
      error: 'Delivery failed',
      target: 'unknown-agent',
      reason: 'Target offline'
    });

    expect(formatted).toEqual({
      from: 'hub',
      text: 'Delivery failed (target=unknown-agent, Target offline)'
    });
  });
});
