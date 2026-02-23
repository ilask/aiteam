# WORKLOG (Summary)

最終更新: 2026/02/23 12:05:02 (JST)

## アーカイブ
- 詳細ログ退避先: `docs/20260223_WORKLOG_0742.md` (402 lines)
- それ以前の詳細ログ:
  - `docs/20260221_WORKLOG_1937.md`
  - `docs/20260222_WORKLOG_0057.md`
  - `docs/20260222_WORKLOG_1524.md`
  - `docs/20260222_WORKLOG_2306.md`

## 現在の状態
- `origin/master`: `93e9b63` (push済み)
- ローカル `master`: `93e9b63` に同期済み
- E2E 主要ケース: `src/__tests__/e2e/inter-agent.spec.ts` pass 実績あり
- 最新生成画像: `nanobanana-output/growi_semantic_search_architectu_15.png`

## 主要作業サマリー

### 2026/02/23 02:14:35 (JST)
- 目的:
  - PC クラッシュ後の継続として、Windows/WezTerm 経由 E2E の不安定要因を解消し、実E2Eを再現可能にする。
- 変更ファイル:
  - `src/adapters/claude.ts`
  - `src/adapters/gemini.ts`
  - `src/adapters/codex.ts`
  - `src/__tests__/e2e/wezterm-harness.ts`
  - `src/__tests__/e2e/inter-agent.spec.ts`
- 実行コマンド:
  - `pnpm run build`
  - `pnpm exec vitest run src/__tests__/adapters/gemini-auth.spec.ts src/__tests__/adapters/codex-delegation.spec.ts src/__tests__/hub.spec.ts src/__tests__/cli-output-filter.spec.ts`
  - `pnpm exec vitest run src/__tests__/e2e/inter-agent.spec.ts --reporter verbose`
- 結果:
  - ユニット: 75 passed
  - E2E: 2/2 passed (inter-agent)
  - `gemini_text` で PNG パス返却をログ確認
- 出力ファイルパス:
  - `tmp/e2e-debug/aiteam-e2e-1771780290748-d0c5a6.ndjson`
  - `nanobanana-output/growi_semantic_search_architectu_15.png`

### 2026/02/23 06:08:45 (JST)
- 目的:
  - README に、ユーザーがそのまま入力できる E2E 再現例を追加する。
- 変更ファイル:
  - `README.md`
- 実行コマンド:
  - `Get-Content README.md -TotalCount 320`
  - `Get-Content src/__tests__/e2e/headless-workflow.spec.ts -TotalCount 260`
  - `Get-Content src/__tests__/e2e/inter-agent.spec.ts -TotalCount 420`
- 結果:
  - `README.md` に `E2E Scenarios (Copy/Paste)` を追加
  - 追加シナリオ: headless smoke / inter-agent collaboration / port fallback
- 出力ファイルパス:
  - `README.md`

### 2026/02/23 07:42:59 (JST)
- 目的:
  - `git push` 非 fast-forward を解消し、ローカルとリモートを整合させる。
- 変更ファイル:
  - Git 参照とブランチ状態のみ（ソース変更なし）
- 実行コマンド:
  - `git stash push -m "safety-before-master-sync-..."`
  - `git fetch origin --prune`
  - `git reset --hard origin/master`
  - `git push`
- 結果:
  - `master` を `origin/master` (`93e9b63`) に同期
  - push は `Everything up-to-date`
- 出力ファイルパス:
  - なし（Git 状態修復）

### 2026/02/23 11:41:47 (JST)
- 目的:
  - ルート直下の作業ノート/生成物を整理し、日常運用で `git status` が見やすい状態に戻す。
- 変更ファイル:
  - `.gitignore`
  - `docs/20260222_CODEX_IMPACT_SCOPE_GROWI.md`
  - `docs/20260223_GROWI_SEMANTIC_SEARCH_REVIEW_MATRIX.md`
  - `docs/WORKLOG.md`
- 実行コマンド:
  - `git status --short`
  - `Get-ChildItem -Force`
  - `Move-Item ... tmp/local-notes/`
  - `Get-Content .gitignore`
- 結果:
  - ルート直下の untracked ノート類（`codex_review_*`, `codex-app-schema.json`, `typescript`）を `tmp/local-notes/` へ退避。
  - `.gitignore` に `tmp/` と `nanobanana-output/` を追加し、生成物の再汚染を防止。
  - 既存の設計メモ 2 件（`docs/20260222_CODEX_IMPACT_SCOPE_GROWI.md`, `docs/20260223_GROWI_SEMANTIC_SEARCH_REVIEW_MATRIX.md`）は docs として保持。
- 出力ファイルパス:
  - `tmp/local-notes/`
  - `docs/20260222_CODEX_IMPACT_SCOPE_GROWI.md`
  - `docs/20260223_GROWI_SEMANTIC_SEARCH_REVIEW_MATRIX.md`

### 2026/02/23 12:05:02 (JST)
- 目的:
  - テスト配置の混在（`tests/`, `test-*.ts`, `src/__tests__`）を解消し、現行/レガシーを明確に分離する。
- 変更ファイル:
  - `legacy/python-tests/**` (旧 `tests/**` を移設)
  - `scripts/probes/test-claude-stdio.ts`
  - `scripts/probes/test-codex-rpc.ts`
  - `scripts/probes/test-codex-stdio.ts`
  - `scripts/probes/test-gemini-stdio.ts`
  - `README.md`
  - `docs/WORKLOG.md`
- 実行コマンド:
  - `git mv tests legacy/python-tests`
  - `git mv test-*.ts scripts/probes/`
  - `pnpm exec vitest run src/__tests__/hub.spec.ts`
- 結果:
  - Active test path を `src/__tests__/` に一本化。
  - 旧 Python/tmux テストは `legacy/python-tests/` へ整理。
  - 直下 probe スクリプトは `scripts/probes/` へ移設。
  - README に `Test Layout` を追加し、現行/レガシーの置き場所を明記。
  - 検証: `hub.spec.ts` 1/1 passed。
- 出力ファイルパス:
  - `legacy/python-tests/`
  - `scripts/probes/`
  - `README.md`

## 参考コミット
- `8b4f500` Stabilize Windows inter-agent E2E flows
- `ba49c16` Add copy-paste E2E examples to README
- `93e9b63` Stabilize Windows inter-agent E2E and add README scenarios (remote master)
- `870a290` docs: rotate WORKLOG and archive details
