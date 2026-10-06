# 其他人怎麼做多 Agent 協作（2026-10-06 調查）

調查方式：網頁搜尋 GitHub 專案與官方文件。以下只列出這次實際查到來源的項目；星數、活躍度沒有逐一核實。

## §1 四種常見做法

### §1.1 平行執行器：每個 agent 一個 git worktree

最主流的做法。一個桌面或終端介面同時開多個 CLI agent（Claude Code、Codex CLI、Gemini CLI…），
**每個 agent 在自己的分支與 worktree 工作**，互不覆蓋檔案，最後由人挑選或合併。

- [Parallel Code](https://www.neura.market/ai-tools-directory/all/parallel-code)：開源桌面程式，每個 agent 獨立分支＋worktree。
- [Paseo](https://github.com/Aias00/paseo)：一個介面管理 Claude Code／Codex／OpenCode，支援桌面、手機、網頁、CLI。
- [Manaflow](https://gitblind.noratr.app/manaflow-ai/manaflow)：同時啟動多家 agent 對同一個程式庫平行作業。
- 社群把這種模式稱為「agentmaxxing」，見 [這篇整理](https://codex.danielvaughan.com/2026/04/11/agentmaxxing-parallel-multi-cli-orchestration/)。

### §1.2 跨模型審查：一個寫、另一個審

不開多個視窗，而是讓一個 agent 在工作途中把另一家模型當工具呼叫。

- [claude-code-cross-review](https://github.com/atompilot/claude-code-cross-review)：Claude 寫、Codex 審、Claude 修，循環到乾淨才 commit。
- 做法是把 Codex 掛成 Claude Code 的 MCP server，或使用 OpenAI 的 Codex plugin，見
  [How to Make Codex CLI and Claude Code Work Together](https://codex.danielvaughan.com/2026/04/18/codex-cli-claude-code-working-together/)。
- 理由：不同供應商的模型互審，比較不會互相附和。

### §1.3 標準協定：ACP（Agent Client Protocol）

Zed 在 2025 年 8 月提出的開放標準，用 JSON-RPC over stdio 定義「編輯器／前端 ↔ agent」的介面。
前端只要實作一次 ACP，就能接上任何有 adapter 的 agent。

- [Agent Client Protocol](https://zed.dev/acp)；已有 `claude-code-acp`、`codex-acp` 等 adapter，
  見 [Codex is live in Zed](https://zed.dev/blog/codex-is-live-in-zed)。
- Neovim、Emacs、JetBrains 以及 Microsoft 的終端機也已採用，見
  [這篇說明](https://codex.danielvaughan.com/2026/06/10/agent-client-protocol-microsoft-intelligent-terminal-codex-cli-multi-agent-ide-ecosystem/)。
- MCP（agent ↔ 工具）、ACP（前端 ↔ agent）、A2A（agent ↔ agent）三者的分工見
  [MCP, ACP, and A2A in Practice](https://codex.danielvaughan.com/2026/05/01/codex-cli-agent-interoperability-protocols-mcp-acp-a2a/)。

### §1.4 本地模型接進官方 CLI

不另寫聊天程式，而是保留官方 CLI 的 agent 能力，只把模型端點換掉。

- **Codex CLI**：在設定中定義 `model_providers`（base URL、wire API、認證），或用 `--oss` 搭配 Ollama／LM Studio。
  見 [官方 Advanced Configuration](https://developers.openai.com/codex/config-advanced)。
- **Claude Code**：設定 `ANTHROPIC_BASE_URL` 與 `ANTHROPIC_AUTH_TOKEN` 指向 Anthropic Messages 相容端點。
  Ollama 自 v0.14.0 起內建相容層，見 [Ollama 官方說明](https://registry.ollama.ai/blog/claude)。
  LM Studio 等只講 OpenAI 格式的伺服器則需要轉譯代理。

## §2 與本專案的對照

| 面向 | 本專案現況 | 其他人的常見做法 |
| --- | --- | --- |
| 介面 | 自製 Qt 桌面程式，三個角色並排 | 桌面／終端／網頁皆有，概念相同 |
| 接 agent 的方式 | 每個 CLI 各寫一個 adapter（Claude 的 stream-json、Codex 的 app-server） | 逐漸改用 ACP，一個實作接多家 |
| 檔案隔離 | 所有角色共用同一個專案目錄 | 每個 agent 一個 worktree |
| 交接 | 全部人工觸發、預覽後傳送 | 多數自動平行；跨審查用 MCP 自動呼叫 |
| 本地模型 | 尚無 | 透過官方 CLI 換端點 |
| 獨有部分 | G8毛（ChatGPT Dot）整合、每步人工同意 | 未見同類 |

## §3 建議（依優先順序）

1. **本地模型視窗照 §1.4 的路做**：重用既有 Codex／Claude adapter，只換端點。
   規格已寫在 [HANDOFF-local-llm-panel.md](HANDOFF-local-llm-panel.md)。預設用 Codex harness，
   因為幾乎所有本地伺服器都講 OpenAI 相容協定。
2. **補上 worktree 隔離**：目前 Claude 與 Codex 指向同一個目錄，兩邊同時改檔會互相覆蓋。
   這是本專案與主流做法差距最大、也最容易出事的一點。
3. **中期評估 ACP**：現在每次官方 CLI 改協定，就要改對應的 adapter。改走 ACP 後，
   新增 Gemini CLI 之類的角色幾乎不用寫程式。代價是要重寫 adapter 層，不建議和第 1 點同時進行。
4. **人工把關的交接保留**：這是本專案刻意的設計，也是與自動平行工具的主要差異，不需要跟著改。
