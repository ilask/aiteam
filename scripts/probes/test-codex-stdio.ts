import { spawn } from 'child_process';
import * as readline from 'readline';

const codex = spawn('codex', ['app-server'], { stdio: ['pipe', 'pipe', 'inherit'], shell: true });

const rl = readline.createInterface({
    input: codex.stdout,
    terminal: false
});

rl.on('line', (line) => {
    console.log('Received:', line);
});

console.log('Sending initialize...');
codex.stdin.write(JSON.stringify({
    jsonrpc: "2.0",
    id: 1,
    method: "initialize",
    params: { clientInfo: { name: "aiteam", version: "1.0.0" }, capabilities: {} }
}) + "\n");

setTimeout(() => {
    console.log('Sending generic request...');
    codex.stdin.write(JSON.stringify({
        jsonrpc: "2.0",
        id: 2,
        method: "help",
        params: {}
    }) + "\n");
}, 2000);

setTimeout(() => {
    codex.kill();
    process.exit(0);
}, 4000);
