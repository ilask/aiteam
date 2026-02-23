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

### 2026/02/23 12:09:39 (JST)
- 目的:
  - `docs/RUNBOOK.md` が消失していたため、WezTerm 経由テスト手順と代替手段の不採用理由を復元する。
- 変更ファイル:
  - `docs/RUNBOOK.md`
  - `docs/WORKLOG.md`
- 実行コマンド:
  - `git log --all --oneline -- docs/RUNBOOK.md`
  - `git show 6c9b62f83436d4e23b420be33923adc01fc3a4b6:docs/RUNBOOK.md`
  - `Get-Content README.md`
  - `Get-Content docs/PROJECT_SPEC.md`
  - `Get-Content docs/WORKLOG.md`
  - `Get-Content src/__tests__/e2e/wezterm-harness.ts`
  - `Get-Content src/__tests__/e2e/inter-agent.spec.ts`
- 結果:
  - `docs/RUNBOOK.md` を新規復元。
  - 受け入れテストの WezTerm CLI 手順を「手動スモーク」「Vitest E2E」に分けて明記。
  - `agent-tui` / `wtmux` / `wt` / `WSL+tmux` を主系にしない理由を簡潔に明記。
- 出力ファイルパス:
  - `docs/RUNBOOK.md`

### 2026/02/23 12:11:27 (JST)
- 目的:
  - `RUNBOOK` 復元コミットを push し、stash 残件を確認する。
- 変更ファイル:
  - `docs/WORKLOG.md`
- 実行コマンド:
  - `git push`
  - `git stash list`
  - `git stash show --stat "stash@{0}"`
- 結果:
  - `master -> origin/master` へ push 完了（`81c4748..222adf2`）。
  - stash は 1 件残存: `stash@{0}: On master: safety-before-master-sync-20260223-074223`
  - 残存 stash の内容は 60 files / 12681 insertions（同期前の安全退避スナップショット）。
- 出力ファイルパス:
  - なし（Git 状態確認）

### 2026/02/23 12:15:40 (JST)
- 目的:
  - ユーザー依頼に基づき、`stash@{0}` の中身を `tests` 系を除外して 1 ファイルずつ確認する。
- 変更ファイル:
  - `docs/WORKLOG.md`
- 実行コマンド:
  - `git diff --name-only --diff-filter=ACM "stash@{0}^1" "stash@{0}"`
  - `git show "stash@{0}:<path>"`
  - `git ls-tree "stash@{0}" -- e2e-dataset/growi-semantic-search-task/growi-submodule`
  - `git rev-parse "stash@{0}:<path>"`, `git rev-parse "HEAD:<path>"`
  - `git diff "stash@{0}" -- docs/RUNBOOK.md`
  - `git diff "stash@{0}" -- src/cli.ts src/index.ts`
- 結果:
  - `tests/**`, `src/__tests__/**`, `test-*.ts` を除外した対象は 30 ファイル。
  - 30 ファイルすべての内容を確認（サブモジュールは gitlink SHA で確認）。
  - 状態内訳: `same_as_head` 17 件, `missing_in_head` 10 件, `differs_from_head` 3 件。
  - `differs_from_head`: `docs/RUNBOOK.md`, `src/cli.ts`, `src/index.ts`。
  - `missing_in_head`: `docs/20260222_*` 一式と `scripts/win/*` など、現行 HEAD には存在しない過去退避物を確認。
- 出力ファイルパス:
  - `tmp/stash0_non_tests_preview.txt`
  - `tmp/stash0_non_tests_structure.txt`

### 2026/02/23 12:22:27 (JST)
- 目的:
  - 旧 Python 系資産と `agent-tui` 運用資産を整理し、`stash@{0}` にのみ存在していた `docs` を取り込む。
- 変更ファイル:
  - 削除: `src/tmux_ai_team/**`, `legacy/python-tests/**`, `pyproject.toml`
  - 追加: `docs/20260222_ARXIV_2601.22832v1_SUMMARY.md`
  - 追加: `docs/20260222_CLAUDE_GROWI_SEMANTIC_ARCHITECTURE.md`
  - 追加: `docs/20260222_GEMINI_DIAGRAM_GROWI.md`
  - 追加: `docs/20260222_WORKLOG_0057.md`
  - 追加: `docs/20260222_WORKLOG_1524.md`
  - 追加: `docs/20260222_WORKLOG_2306.md`
  - 更新: `README.md`, `.gitignore`, `docs/RUNBOOK.md`, `docs/WORKLOG.md`
- 実行コマンド:
  - `git rm -r src/tmux_ai_team legacy/python-tests pyproject.toml`
  - `git checkout "stash@{0}" -- docs/20260222_*.md`
  - `rg -n "agent-tui|agent_tui|legacy/python-tests|tmux_ai_team|pyproject.toml" README.md docs/RUNBOOK.md .gitignore src package.json scripts`
  - `git diff --name-only --diff-filter=ACM "stash@{0}^1" "stash@{0}"`
- 結果:
  - Node/TS 現行運用に不要な Python 実装・テスト群をリポジトリから除去。
  - `README.md` の legacy Python / `agent-tui` セクションを削除。
  - `.gitignore` から Python 向け ignore を削除。
  - `docs/RUNBOOK.md` から `agent-tui` 記述を除去。
  - `HEAD` に無かった `docs/20260222_*` 6ファイルを取り込み完了。
- 出力ファイルパス:
  - `docs/20260222_ARXIV_2601.22832v1_SUMMARY.md`
  - `docs/20260222_CLAUDE_GROWI_SEMANTIC_ARCHITECTURE.md`
  - `docs/20260222_GEMINI_DIAGRAM_GROWI.md`
  - `docs/20260222_WORKLOG_0057.md`
  - `docs/20260222_WORKLOG_1524.md`
  - `docs/20260222_WORKLOG_2306.md`

### 2026/02/23 12:25:58 (JST)
- 目的:
  - 現行 TS/Vitest ベースに合わない残存物を追加整理する。
- 変更ファイル:
  - 削除: `aiteam`, `codex_prompt.txt`, `codex_review_phase5.txt`
  - 更新: `docs/WORKLOG.md`
- 実行コマンド:
  - `git rm aiteam codex_prompt.txt codex_review_phase5.txt`
  - `rg -n "tmux_ai_team|python3 -m tmux_ai_team|codex_prompt\\.txt|codex_review_phase5\\.txt" README.md AGENTS.md docs package.json scripts src`
  - `pnpm exec vitest run src/__tests__/hub.spec.ts`
- 結果:
  - Python エントリの旧ラッパー（`aiteam`）を削除。
  - 一時検証メモ（`codex_prompt.txt`, `codex_review_phase5.txt`）を削除。
  - 動作確認として `hub.spec.ts` は 1/1 pass。
- 出力ファイルパス:
  - なし（不要資産削除）

### 2026/02/23 12:28:46 (JST)
- 目的:
  - ユーザー依頼に基づき、最新コミットを push し、現行テストケース数を集計する。
- 変更ファイル:
  - `docs/WORKLOG.md`
- 実行コマンド:
  - `git push`
  - `Get-ChildItem -Recurse src/__tests__ -Filter *.spec.ts`
  - `rg -n "\\bit\\s*\\(" src/__tests__ -g "*.spec.ts"`
  - `pnpm exec vitest run src/__tests__/hub.spec.ts`
- 結果:
  - `master -> origin/master` へ push 完了（`d5d4dcf..97d1e54`）。
  - 現行テストファイルは `src/__tests__/` 配下 7 ファイル。
  - `it(...)` ベースのテストケース数は 16 件。
  - 参考検証として `hub.spec.ts` は 1/1 pass。
- 出力ファイルパス:
  - なし（件数集計）

### 2026/02/23 12:35:25 (JST)
- 目的:
  - 旧 Python テストで未移植だった観点（help/入力耐性/失敗時ヒント）を TS/Vitest で補完する。
- 変更ファイル:
  - `src/__tests__/hub.spec.ts`
  - `src/__tests__/e2e/cli-ux-resilience.spec.ts`
  - `docs/WORKLOG.md`
- 実行コマンド:
  - `pnpm run build`
  - `pnpm exec vitest run src/__tests__/hub.spec.ts src/__tests__/e2e/cli-ux-resilience.spec.ts`
- 結果:
  - `hub.spec.ts` に「宛先未接続時に Delivery failed を返し、warning 文言を出す」ケースを追加。
  - 新規 `cli-ux-resilience.spec.ts` で以下を追加:
    - 起動時の案内文言契約
    - 無効入力時のヒント文言契約
    - 不正入力連続後でも終了できる入力耐性
  - 追加分を含む対象テストは `5/5 passed`。
- 出力ファイルパス:
  - なし（テスト追加）

### 2026/02/23 13:25:18 (JST)
- 目的:
  - 手動 probe スクリプトをテスト資産配置に合わせて `src/__tests__/` 配下へ集約する。
- 変更ファイル:
  - 移動: `scripts/probes/test-claude-stdio.ts` -> `src/__tests__/probes/test-claude-stdio.ts`
  - 移動: `scripts/probes/test-codex-rpc.ts` -> `src/__tests__/probes/test-codex-rpc.ts`
  - 移動: `scripts/probes/test-codex-stdio.ts` -> `src/__tests__/probes/test-codex-stdio.ts`
  - 移動: `scripts/probes/test-gemini-stdio.ts` -> `src/__tests__/probes/test-gemini-stdio.ts`
  - 更新: `README.md`
  - 更新: `docs/WORKLOG.md`
- 実行コマンド:
  - `git mv scripts/probes src/__tests__/probes`
  - `rg -n "scripts/probes|src/__tests__/probes|Manual adapter probe" README.md docs package.json`
- 結果:
  - 手動 probe スクリプトを `src/__tests__/probes/` へ移設。
  - README の Test Layout を新配置へ更新。
  - probe は `*.spec.ts` / `*.test.ts` 命名ではないため、Vitest の通常実行対象には含まれない。
- 出力ファイルパス:
  - `src/__tests__/probes/`

### 2026/02/23 20:06:04 (JST)
- 目的:
  - ユーザー報告の実行時不具合を修正する（旧UX混在、`/status` 非対応、重複表示、ポート競合、Claude権限確認、Gemini `AttachConsole failed`）。
- 変更ファイル:
  - 更新: `src/cli.ts`
  - 更新: `src/index.ts`
  - 更新: `src/adapters/claude.ts`
  - 更新: `src/adapters/gemini.ts`
  - 更新: `src/__tests__/e2e/cli-ux-resilience.spec.ts`
  - 更新: `src/__tests__/e2e/headless-workflow.spec.ts`
  - 更新: `README.md`
  - 更新: `docs/WORKLOG.md`
- 実行コマンド:
  - `pnpm run build`
  - `pnpm exec vitest run src/__tests__/hub.spec.ts src/__tests__/cli-output-filter.spec.ts src/__tests__/e2e/cli-ux-resilience.spec.ts src/__tests__/e2e/headless-workflow.spec.ts`
  - `pnpm exec vitest run src/__tests__/adapters/codex.spec.ts src/__tests__/adapters/claude.spec.ts src/__tests__/adapters/gemini.spec.ts`
  - `node dist/cli.js -h`
  - `npm install -g . --force`
  - `aiteam -h`
- 結果:
  - CLI を「plain text -> main agent（既定 codex）」UXへ更新し、`/status` を実装。
  - `aiteam -h` を実装し、AI向けのロール/通信モデルを表示可能化。
  - 4501競合時に空きポートへ自動フォールバックする挙動を実装（`[aiteam] Port ... is in use`）。
  - CLI表示重複抑制を導入（短時間の同一 `[from,text]` のみ抑制）。
  - `/status` に `routed.prompt` と `routed.delegate` を表示し、delegateカウントの意味を明記。
  - Claude 起動引数に `--permission-mode` を導入し、既定を `bypassPermissions` 化（`AITEAM_CLAUDE_PERMISSION_MODE` で上書き可能）。
  - Gemini は `stdin` 送信から `-p` one-shot 実行へ変更し、Windows では Node entrypoint fallback を使用するよう変更。
  - グローバル実行時の無反応はエントリ判定のシンボリックリンク差分が原因だったため、`realpath` 比較に修正。
  - 上記変更後、対象テストは pass（`15/15` + adapter `3/3`）。
- 出力ファイルパス:
  - `dist/cli.js`
  - `dist/index.js`

### 2026/02/23 19:59:48 (JST)
- 目的:
  - 確認依頼のファイル群をレビューし、重複出力抑止・`/status` 表示・ポートフォールバック・Gemini `-p`/Windows対策・Claude許可モードに潜在的な回帰がないかを評価する。
- 変更ファイル:
  - `docs/WORKLOG.md`
- 実行コマンド:
  - `type README.md`
  - `type docs/PROJECT_SPEC.md`
  - `type docs/RUNBOOK.md`
  - `Get-Content docs/WORKLOG.md -Tail 60`
  - `type src/cli.ts`
  - `type src/index.ts`
  - `type src/adapters/claude.ts`
  - `type src/adapters/gemini.ts`
  - `type src/__tests__/e2e/cli-ux-resilience.spec.ts`
  - `type src/__tests__/e2e/headless-workflow.spec.ts`
  - `python -c "from itertools import islice; lines=open('src/cli.ts').read().splitlines(); ...(dedup and /status slices)"`
  - `python -c "from itertools import islice; lines=open('src/adapters/gemini.ts').read().splitlines(); ...(Gemini prompts/entrypoint slices)"`
  - `python -c "from itertools import islice; lines=open('src/adapters/claude.ts').read().splitlines(); ...(Claude permission lines)"`
- 結果:
  - CLIの2秒以内同文メッセージ抑止（`src/cli.ts` 540 行付近）が再送された正当な応答も表示せず、`/status`の `routed.delegate` はユーザーが `@agent` で送ったルートを含まないため、期待した情報を返せないリスクが残る。
  - Windowsフォールバック、Gemini の `-p` エントリ、Claude の `bypassPermissions` デフォルトはいずれも該当コード通りに維持されており、追加の懸念点は確認できなかった。
- 出力ファイルパス:
  - なし（レビュー記録）
