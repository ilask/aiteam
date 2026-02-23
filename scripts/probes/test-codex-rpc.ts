import { spawn } from 'child_process';
import { WebSocket } from 'ws';

const port = 4505;
const codex = spawn('codex', ['app-server', '--listen', `ws://127.0.0.1:${port}`], { stdio: 'inherit', shell: true });

setTimeout(() => {
    const ws = new WebSocket(`ws://127.0.0.1:${port}`);
    ws.on('open', () => {
        console.log('Connected to Codex WS');
        ws.send(JSON.stringify({
            jsonrpc: "2.0",
            id: 1,
            method: "initialize",
            params: { clientInfo: { name: "aiteam", version: "1.0.0" }, capabilities: {} }
        }));
    });
    ws.on('message', (data) => {
        console.log('Received:', data.toString());
        const parsed = JSON.parse(data.toString());
        if (parsed.id === 1) {
            ws.send(JSON.stringify({
                jsonrpc: "2.0",
                method: "initialized",
                params: {}
            }));
            console.log('Sent initialized');
            
            // Try to send a simple request
            ws.send(JSON.stringify({
                jsonrpc: "2.0",
                id: 2,
                method: "help", // or something else
                params: {}
            }));
        }
    });
    ws.on('close', () => console.log('Codex WS closed'));
    ws.on('error', (err) => console.error('Codex WS error:', err));
}, 2000);

setTimeout(() => {
    codex.kill();
    process.exit(0);
}, 5000);
