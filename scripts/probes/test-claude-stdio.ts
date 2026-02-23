import { spawn } from 'child_process';
import * as readline from 'readline';

const claude = spawn('claude', ['--print', '--verbose', '--input-format=stream-json', '--output-format=stream-json'], {
    stdio: ['pipe', 'pipe', 'inherit'],
    shell: process.platform === 'win32'
});

const rl = readline.createInterface({
    input: claude.stdout,
    terminal: false
});

rl.on('line', (line) => {
    console.log('OUT:', line);
});

claude.on('error', (err) => {
    console.error('Claude spawn error:', err);
});

claude.on('exit', (code) => {
    console.log('Claude exited with code:', code);
});

// We need to send an input event. How does Claude Code stream-json input look like?
// Let's send a basic prompt.
const input = {
    type: "user",
    message: {
        role: "user",
        content: "What is 2+2? Reply with just the number."
    }
};

setTimeout(() => {
    console.log('Sending message...');
    claude.stdin.write(JSON.stringify(input) + String.fromCharCode(10));
}, 1000);

setTimeout(() => {
    claude.kill();
    process.exit(0);
}, 6000);
