import { spawn } from 'child_process';
import * as readline from 'readline';

const cmd = process.platform === 'win32' ? 'gemini.cmd' : 'gemini';
const gemini = spawn(cmd, ['-o', 'stream-json'], {
    stdio: ['pipe', 'pipe', 'inherit'],
    shell: process.platform === 'win32'
});

const rl = readline.createInterface({
    input: gemini.stdout,
    terminal: false
});

rl.on('line', (line) => {
    console.log('OUT:', line);
});

gemini.on('error', (err) => {
    console.error('Gemini spawn error:', err);
});

gemini.on('exit', (code) => {
    console.log('Gemini exited with code:', code);
});

// Assuming Gemini accepts JSON on stdin like Claude does? Let's try text first or JSON.
// The docs said: "Appended to input on stdin (if any)." when using -p.
// Let's try sending a plain text prompt via stdin.
setTimeout(() => {
    console.log('Sending message...');
    gemini.stdin.write("What is 2+2? Reply with just the number." + String.fromCharCode(10));
}, 1000);

setTimeout(() => {
    gemini.kill();
    process.exit(0);
}, 6000);
