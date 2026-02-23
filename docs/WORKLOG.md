# WORKLOG (Summary)

このファイルは要約版です。詳細ログは `docs/20260224_WORKLOG_0004.md` を参照。

## 主要マイルストーン（要約）
- 2026-02-21〜2026-02-22:
  - aiteam v2 (Node.js/TypeScript) 基盤を整備。
  - Central Hub (WebSocket/JSON-RPC) と `codex`/`claude`/`gemini` 各アダプターを実装。
  - tmux依存の旧運用からヘッドレス密結合アーキテクチャへ移行。
- 2026-02-22:
  - Inter-Agent Router の挙動改善。
  - Windows経路 (`PowerShell -> wezterm cli -> aiteam`) のE2E再現性を強化。
  - `docs/RUNBOOK.md` 整備。
- 2026-02-23:
  - CLI UX改善（`/status`、待機表示、重複表示抑制、Hub配信エラー表示）。
  - Codex起動既定値を最適化（`approval_policy="never"`, `model_reasoning_effort="medium"`）。
  - Claude/GeminiアダプターのWindows挙動を調整し、関連テストを更新。
  - READMEの運用記述を現行仕様へ同期。

## 直近エントリ

### 2026/02/23 23:57:11 (JST)
- 目的:
  - ユーザー報告の「codex応答が見えない/遅い」現象を優先して、待機UXとCodex起動設定を改善する。
- 変更ファイル:
  - 更新: `src/adapters/codex.ts`
  - 更新: `src/cli.ts`
  - 更新: `src/__tests__/cli-output-filter.spec.ts`
  - 更新: `README.md`
  - 更新: `docs/WORKLOG.md`
- 実行コマンド:
  - `pnpm run build`
  - `pnpm exec vitest run src/__tests__/cli-output-filter.spec.ts src/__tests__/adapters/codex.spec.ts src/__tests__/e2e/headless-workflow.spec.ts src/__tests__/e2e/cli-ux-resilience.spec.ts`
  - `node tmp/codex_medium_probe.cjs`
- 結果:
  - Codex adapter の既定起動パラメータ最適化と待機表示改善を反映。
  - 対象テスト pass（`4 files / 16 tests`）。
  - `sup` の初回 `agent_message` が約10秒で返ることを実測。
- 出力ファイルパス:
  - `dist/cli.js`

### 2026/02/24 00:18:44 (JST)
- 目的:
  - ユーザー要望に合わせて、Codex の既定 `model_reasoning_effort` を `medium` から `high` に変更する。
- 変更ファイル:
  - 更新: `src/adapters/codex.ts`
  - 更新: `README.md`
  - 更新: `docs/WORKLOG.md`
- 実行コマンド:
  - `pnpm run build`
- 結果:
  - `DEFAULT_CODEX_REASONING_EFFORT` を `high` に変更。
  - README の既定値説明を `high` に更新。
  - `build` 成功。
- 出力ファイルパス:
  - `dist/cli.js`

### 2026/02/24 00:04:25 (JST)
- 目的:
  - リポジトリ説明依頼に対応するため、`README.md` / `docs/PROJECT_SPEC.md` / `docs/RUNBOOK.md` / `docs/WORKLOG.md` と主要実装 (`src/cli.ts`, `src/index.ts`, `src/adapters/codex.ts`) を確認して要点を整理する。
  - `docs/WORKLOG.md` が 400 行超過のため、運用ルールに従い要約化・退避を実施する。
- 変更ファイル:
  - 追加: `docs/20260224_WORKLOG_0004.md`
  - 更新: `docs/WORKLOG.md`
- 実行コマンド:
  - `Get-ChildItem -Force`
  - `rg --files`
  - `Get-Content -Raw README.md`
  - `Get-Content -Raw docs/PROJECT_SPEC.md`
  - `Get-Content -Raw docs/RUNBOOK.md`
  - `Get-Content -Tail 120 docs/WORKLOG.md`
  - `Get-Content -Raw package.json`
  - `Get-Content -Raw src/index.ts`
  - `Get-Content -Raw src/cli.ts`
  - `Get-Content -Raw src/adapters/codex.ts`
- 結果:
  - リポジトリの目的・構成・実行手順・テスト方針を要約可能な状態に整理。
  - `docs/WORKLOG.md` を要約版へ更新し、詳細ログを `docs/20260224_WORKLOG_0004.md` に退避。
- 出力ファイルパス:
  - `docs/20260224_WORKLOG_0004.md`
  - `docs/WORKLOG.md`
