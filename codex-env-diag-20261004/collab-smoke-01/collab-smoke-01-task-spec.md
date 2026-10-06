# TASK_SPEC — COLLAB-SMOKE-20261005-01

## §1 task_id
`COLLAB-SMOKE-20261005-01`

## §2 repo 路徑
`C:\Users\ryant\Desktop\codex-env-diag-20261004\test-repo`（機器 Ryan-PC）

現況（Claude 於 2026-10-05 實測）：
- 分支 `master`，**尚無任何 commit**。
- 目錄內只有 `.git` 與 `README.md`。
- `README.md` 已存在、**未追蹤**，目前內容為單行 `diagnostic test repo`（21 bytes）。
- `git status --short` 目前輸出：`?? README.md`

## §3 目標
把 `README.md` 的內容**整個取代**為下列 7 行（第 2、6 行為空行），不多不少：

```text
# AI Collaboration Smoke Test

Claude: primary reviewer
dot: relay and secondary reviewer
Codex: implementer

Status: collaboration pipeline test
```

## §4 允許修改的檔案
- 只有 `README.md`（repo 根目錄）。

## §5 禁止事項
- N1 不得建立、修改、刪除 `README.md` 以外的任何檔案（含 `.gitignore`、`docs/`、暫存檔）。
- N2 不得 `git add`、`git commit`、`git push`、建立分支或 tag、修改 git config。
- N3 不得操作此 repo 以外的任何路徑；不得碰 ORDER-SYSTEM、KPR-WEBSITE 或其他正式專案。
- N4 不得安裝套件、不得修改 Codex / sandbox / MCP / 安全設定、不得解除沙箱執行。
- N5 不得讀取 token、`auth.json`、cookie、`.env`。
- N6 不得擴大範圍：不加徽章、日期、額外章節、授權聲明或任何 §3 以外的文字。
- N7 任一步驟失敗就停止並回報原始錯誤，不重試、不自行改用其他做法。

## §6 acceptance criteria
- A1 `README.md` 內容與 §3 的 7 行逐字相同（換行 LF 或 CRLF 皆可；檔尾恰一個換行；**無 BOM**；行尾無多餘空白）。
- A2 `git status --short` 的輸出恰為一行：`?? README.md`
- A3 repo 仍無任何 commit（`git log` 回報尚無 commit），index 為空。
- A4 repo 根目錄除 `.git` 與 `README.md` 外沒有其他檔案或目錄。

## §7 Codex 回報格式（必須是實際執行的原始輸出，不接受摘要）
- R1 `git diff -- README.md` 的原始輸出與結束碼。
  注意：`README.md` 是未追蹤檔，此指令**預期輸出為空**；請照實回報，不要捏造 diff。
- R2 `git diff --no-index -- /dev/null README.md` 的原始輸出與結束碼
  （有差異時結束碼為 1，屬正常）。這是本任務實際 diff 的依據。
- R3 `git status --short` 的原始輸出與結束碼。
- R4 實際修改內容：`README.md` 修改後的完整內容（僅 7 行，可全貼）。
- R5 測試/驗證結果：對照 A1–A4 逐項 `[x]` / `[ ]`，每項附所依據的指令輸出。
- R6 若有任何未完成或偏離，明確列出；禁止「大致完成」。

## §8 執行備註
- 寫入 `README.md` 需要可寫入工作目錄的沙箱模式（例如 `workspace-write`）；
  這是單次執行參數，不得為此修改 `config.toml` 或解除沙箱。
- 觸發語：「照 TASK_SPEC COLLAB-SMOKE-20261005-01 執行」。
