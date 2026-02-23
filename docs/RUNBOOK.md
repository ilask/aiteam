# RUNBOOK

## 目的
- Windows の受け入れテスト/E2E を `wezterm cli` 経由で再現可能にする。
- 運用経路を `Windows PowerShell -> wezterm cli -> aiteam` に統一する。
- 代替手段は「不採用理由」を簡潔に残す。

## 推奨実行経路 (2026-02-23)
- メイン: `Windows PowerShell -> wezterm cli -> node dist/cli.js`
- E2E: `src/__tests__/e2e/wezterm-harness.ts` を使うテストを実行
  - `src/__tests__/e2e/inter-agent.spec.ts`

## 前提
- OS: Windows
- Node.js: v20+
- `pnpm` 利用可能
- `wezterm.exe` が利用可能
  - 既定: `C:\Program Files\WezTerm\wezterm.exe`
  - 別パスの場合: `AITEAM_WEZTERM_EXE` で指定
- `codex` / `claude` / `gemini` CLI が PATH で解決可能
- ビルド済み: `pnpm run build`

## 受け入れテスト (手動スモーク, WezTerm CLI)
1. ビルド:
```powershell
pnpm run build
```
2. WezTerm で pane を起動:
```powershell
$pane = wezterm cli --prefer-mux spawn --new-window --cwd "$PWD" -- cmd /k
```
3. `aiteam` 起動:
```powershell
wezterm cli --prefer-mux send-text --pane-id $pane --no-paste "node dist\cli.js codex`r"
```
4. 起動確認:
```powershell
wezterm cli --prefer-mux get-text --pane-id $pane --start-line -220
```
5. `/status` と通常入力を送信:
```powershell
wezterm cli --prefer-mux send-text --pane-id $pane --no-paste "/status`r"
wezterm cli --prefer-mux send-text --pane-id $pane --no-paste "sup`r"
wezterm cli --prefer-mux get-text --pane-id $pane --start-line -260
```
6. 終了:
```powershell
wezterm cli --prefer-mux send-text --pane-id $pane --no-paste "exit`r"
wezterm cli --prefer-mux kill-pane --pane-id $pane
```

### 成功条件
- `--- aiteam CLI ---` が表示される
- `[status]` ブロックが表示される
- `[codex]` 応答が表示される
- `Shutting down...` が表示される

## Vitest E2E (WezTerm CLI)
```powershell
pnpm run build
pnpm exec vitest run src/__tests__/e2e/inter-agent.spec.ts --reporter verbose
```

### 成功条件
- `/status` で `codex/claude/gemini` が connected
- `codex->claude` と `codex->gemini` の routed evidence が観測される
- `nanobanana-output/` に新規 PNG が生成される
- `tmp/e2e-debug/*.ndjson` に debug log が出力される

## WSL 経由で PowerShell を使って再現する場合
WSL から次のように Windows 側 PowerShell を直接呼ぶ。
```bash
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -Command "cd 'C:\Users\notak\OneDrive\デスクトップ\tmux-ai-team-tool-repo'; pnpm run build; pnpm exec vitest run src/__tests__/e2e/inter-agent.spec.ts --reporter verbose"
```

## トラブルシュート
- `Port 4501 is in use`:
  - 想定内。`aiteam` は空きポートへ自動フォールバックする。
- WezTerm が見つからない:
  - `AITEAM_WEZTERM_EXE` を設定して再実行する。
- 応答待ちで失敗:
  - 生成系プロンプトは時間がかかるため、Vitest タイムアウトと待機時間を増やす。
- デバッグ確認:
  - `tmp/e2e-debug/*.ndjson` の `eventType=message_routed` / `fromConnection=gemini` を確認する。

## 他ツールを主系にしない理由 (簡潔版)
- `wtmux`:
  - セッション共有/Detach-Attach など必要機能が未成熟で、受け入れ運用に不向き。
- `Windows Terminal (wt)`:
  - タブ/ペイン制御は可能だが、テストで必要な「取得・待機・判定」を CLI 単体で完結しづらい。
- `WSL + tmux`:
  - 技術的には可能だが、今回のゴールである「Windows ネイティブ再現」の経路から外れる。

## 参照
- `src/__tests__/e2e/wezterm-harness.ts`
- `src/__tests__/e2e/inter-agent.spec.ts`
- `docs/WORKLOG.md`
