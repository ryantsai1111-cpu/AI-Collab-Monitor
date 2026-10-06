# AI Collaboration Workspace
## Final PRD / System Specification
### Version 1.0

## 1. Product Vision

建立一個 Windows 桌面應用程式，讓使用者可以在**同一個視窗**中，同時操作與監看：

- Claude
- dot
- Codex

三個 Agent 各自擁有獨立互動面板，外觀與操作邏輯盡可能貼近其原本 Desktop / CLI 體驗。

系統的核心價值不是「重新定義 Agent 怎麼說話」，而是：

> 將三個原本分散的 Agent 工作環境整合到單一 Workspace 中，保留各自原生能力，同時增加跨 Agent 協作、handoff、專案同步、session 對應、歷史記錄與可觀察性。

---

## 2. Product Positioning

本產品名稱：

**AI Collaboration Workspace**

不是：

- 單純 log viewer
- 單純 monitor
- 三模型聊天框
- 新的 AI Agent
- 自己重做 Claude / ChatGPT / Codex

而是：

> **Multi-Agent Desktop Workspace + Collaboration Layer**

---

## 3. Core Principles

### 3.1 Agent 原生行為優先

Workspace 不應要求 Claude、dot、Codex 使用特殊格式回答。

例如不強制：

```text
[INPUT]
[REASONING]
[OUTPUT]
```

Agent 應保持原本回答風格。

Workspace 額外記錄：

- 原始輸入
- 原始輸出
- tool calls
- command events
- file events
- session
- project
- timestamp
- handoff

### 3.2 不模擬不存在的功能

UI 中的：

- Model
- Effort
- Thinking
- Project
- Session
- Tool permissions

只能顯示後端實際支援的選項。

如果某一個 Agent 不支援某能力，顯示：

```text
Unsupported
```

不能假造一個選單。

### 3.3 Desktop 能力保留優先

整合時優先順序：

1. 官方 Desktop / CLI / SDK / API 能力
2. 已確認穩定的 local adapter
3. 第三方橋接
4. 非公開介面

如果只能使用非公開介面，UI 必須標示：

```text
Unofficial integration
```

---

## 4. Main Interface

主畫面固定三欄。

```text
┌────────────────────────────────────────────────────────────────────────────┐
│ AI Collaboration Workspace                                                │
│ Project: ORDER-SYSTEM ▼   Task: TASK-021 ▼   Workspace: Dev ▼             │
├──────────────────────┬──────────────────────┬──────────────────────────────┤
│ CLAUDE               │ DOT                  │ CODEX                        │
│ Model: ... ▼         │ Model: ... ▼         │ Model: ... ▼                 │
│ Effort: ... ▼        │ Mode: ...            │ Effort: ... ▼                │
│ Session: ... ▼       │ Session: ... ▼       │ Session: ... ▼               │
│ Project: ... ▼       │ Context: ...         │ Project: ... ▼               │
├──────────────────────┼──────────────────────┼──────────────────────────────┤
│                      │                      │                              │
│ Conversation         │ Conversation         │ Conversation / Execution     │
│                      │                      │                              │
│ User                 │ User                 │ User                         │
│ Assistant            │ Assistant            │ Assistant                    │
│ Tool Call            │ Tool Call            │ Tool Call                    │
│ File Event           │ Event                │ Shell Command                │
│                      │                      │ Diff                         │
│                      │                      │ Tests                        │
│                      │                      │                              │
├──────────────────────┼──────────────────────┼──────────────────────────────┤
│ Input box            │ Input box            │ Input box                    │
│ Attach               │ Attach               │ Attach                       │
│ Send                 │ Send                 │ Send                         │
│ Stop                 │ Stop                 │ Stop                         │
└──────────────────────┴──────────────────────┴──────────────────────────────┘
```

---

## 5. Panel Definition

每個 Agent Panel 是一個完整的 interactive console。

### 5.1 Common Capabilities

每欄至少支援：

- New Session
- Resume Session
- Rename Session
- Session History
- Model Selector
- Effort / Thinking Selector
- Project / Working Directory
- Conversation History
- Text Input
- Send
- Stop
- Copy Response
- Open Raw Event
- Open Logs
- Open Files / Project

只有在後端支援時才顯示：

- File upload
- Image input
- MCP tools
- Tool approval
- Web access
- Terminal
- Voice
- Attachments

---

## 6. Claude Panel

Claude Panel 的目標是：

> 盡可能保留 Claude Code / Claude Desktop 的實際能力。

應支援：

- Claude session 列表
- model 選擇
- effort / thinking 選擇，如果後端支援
- current working directory
- project
- MCP
- tool events
- file edits
- command outputs
- conversation history
- new / resume session

如果使用 Claude Code：

Workspace 應透過 adapter 與 CLI / programmatic mode 互動。

不應解析螢幕文字模擬 Claude。

---

## 7. Dot Panel

Dot Panel 應保留原本 dot 對話體驗。

至少支援：

- Dot conversation
- send message
- read message
- session / thread
- status
- message history
- current task metadata

如果 Model 或 Effort 無法由 dot API 控制：

UI 應顯示：

```text
Managed by ChatGPT / dot
```

不能放假的 selector。

若使用 `chatgpt-dot-cli`：

必須清楚標示：

```text
Unofficial integration
```

---

## 8. Codex Panel

Codex Panel 應最完整呈現實作過程。

支援：

- session
- model
- effort
- project / cwd
- prompt
- assistant response
- shell command
- command output
- exit code
- file read
- file write
- patch
- git diff
- test
- raw JSONL
- sandbox state
- tool approval
- stop

應優先使用官方：

```text
codex exec
```

或官方 App Server / API，如果實際支援。

---

## 9. Global Project Selector

Workspace 上方提供：

```text
Project ▼
```

Project 定義：

```text
Project ID
Name
Repo path
Default branch
Active branch
Claude cwd
Codex cwd
Dot metadata
Notes
```

例如：

```text
Project:
ORDER-SYSTEM

Repo:
C:\Projects\order-system

Branch:
task/international-order
```

---

## 10. Sync Project

提供：

```text
Sync Project to Agents
```

行為：

Claude：

```text
cwd = project repo
```

Codex：

```text
cwd = project repo
```

Dot：

如果沒有 filesystem capability，只同步：

```text
Project name
Repo name
Branch
Task metadata
```

不假裝 dot 已進入 repo。

---

## 11. Session Mapping

Workspace 要維護：

```text
Workspace Task
│
├─ Claude Session ID
├─ Dot Conversation ID
└─ Codex Session ID
```

例如：

```text
TASK-021

Claude:
session_abc

Dot:
thread_xyz

Codex:
session_987
```

這樣三方可以恢復同一件工作。

---

## 12. Task System

Workspace 應有 Task。

Task schema：

```text
task_id
title
project_id
repo
branch
created_at
status

claude_session
dot_session
codex_session

created_by
current_owner
```

---

## 13. Task Status

固定狀態：

```text
NEW
PLANNING
REVIEWING
READY
IMPLEMENTING
VERIFYING
WAITING_USER
BLOCKED
DONE
FAILED
CANCELLED
```

Workspace 可以顯示狀態。

但不能自行決定：

```text
APPROVED
```

除非 Agent 或 orchestrator 明確回報。

---

## 14. Handoff

這是核心功能。

每一個 Agent 回覆旁提供：

```text
Send to Claude
Send to Dot
Send to Codex
```

使用者可以手動選擇。

Handoff 必須傳：

```text
Original content
Source Agent
Target Agent
Task ID
Project
Branch
Timestamp
Source Session
```

---

## 15. Handoff Modes

至少兩種。

### Manual

使用者按：

```text
Send to Dot
```

才傳。

### Assisted

Workspace 先準備：

```text
handoff preview
```

使用者確認後傳。

Final 版預留：

```text
Automatic
```

但預設關閉。

---

## 16. Original Content Preservation

Handoff 不得直接覆寫原文。

資料必須保存：

```text
source_message
handoff_message
```

如果後續有補充說明：

```text
annotation
```

另存。

---

## 17. Conversation Rendering

每一個 Panel 要顯示原始對話。

訊息類型：

```text
user
assistant
tool
system
command
file
event
error
```

不應把所有 event 都轉成 chat bubble。

Codex command 可顯示為：

```text
> git status --short
exit 0
```

---

## 18. Tool Activity

Tool Call 顯示：

```text
Tool
Arguments
Started
Completed
Result
Status
Duration
```

Secrets 必須 redact。

---

## 19. Command Trace

Codex / Claude shell event：

```text
Command
cwd
Started
Ended
Exit Code
stdout
stderr
```

可折疊。

---

## 20. Diff Viewer

Workspace 內建 Diff Viewer。

功能：

- Changed files
- Added / Removed
- Side-by-side
- Unified
- Open file
- Copy diff
- Save patch

不能直接在 diff viewer 編輯原始程式碼。

---

## 21. Test Viewer

顯示：

```text
Command
Framework
Passed
Failed
Skipped
Duration
Exit Code
```

例如：

```text
pytest
128 passed
0 failed
3 skipped
```

---

## 22. Timeline

Timeline 仍保留。

但不是主畫面。

事件：

```text
Prompt sent
Response received
Tool started
Tool completed
Command
File edit
Handoff
Session changed
Project changed
Error
Stop
```

---

## 23. Raw Events

每個 Panel 提供：

```text
Raw Events
```

例如：

- Claude programmatic output
- dot message JSON
- Codex JSONL

Raw 不修改。

---

## 24. History

Workspace 要能打開過去 Task。

```text
Task History
```

支援：

- Search
- Filter by Project
- Filter by Agent
- Filter by Status
- Date
- Branch
- Error

---

## 25. Search

全文搜尋：

```text
conversation
command
file name
response
error
task
project
```

---

## 26. Model Selector

Selector 必須由 adapter 動態回報 capability。

禁止 hardcode。

例如：

```text
capabilities.models
```

如果 adapter 無法取得 model list：

顯示：

```text
Default backend model
```

---

## 27. Effort Selector

同理。

可選值只能來自 backend。

例如：

```text
low
medium
high
xhigh
```

只有實際支援時顯示。

---

## 28. Capability Discovery

每個 adapter 必須提供：

```text
supports_model_selection
supports_effort
supports_sessions
supports_files
supports_tools
supports_project
supports_cancel
supports_streaming
supports_history
```

UI 根據 capability rendering。

---

## 29. Agent Adapter Contract

三個 adapter 統一介面：

```text
connect()
disconnect()

list_models()
list_efforts()

list_sessions()
create_session()
resume_session()

send_message()
stop()

set_project()

stream_events()

get_history()
```

---

## 30. Adapter Layer

結構：

```text
adapters/

claude/
dot/
codex/
```

每個 Agent 的 backend 實作互不耦合。

---

## 31. UI 不直接呼叫 Agent

架構：

```text
UI
 ↓
Workspace Core
 ↓
Adapter
 ↓
Agent backend
```

避免：

```text
React → shell → codex
```

直接耦合。

---

## 32. Local Data Store

推薦：

```text
SQLite
+
Raw JSONL
```

SQLite：

```text
projects
tasks
sessions
messages
events
handoffs
artifacts
settings
```

Raw：

```text
raw/
```

---

## 33. Message Schema

```json
{
  "id": "",
  "task_id": "",
  "agent": "",
  "session_id": "",
  "role": "",
  "content": "",
  "timestamp": "",
  "raw_ref": ""
}
```

---

## 34. Event Schema

```json
{
  "id": "",
  "task_id": "",
  "agent": "",
  "session_id": "",
  "type": "",
  "status": "",
  "timestamp": "",
  "summary": "",
  "raw_ref": ""
}
```

---

## 35. Handoff Schema

```json
{
  "id": "",
  "task_id": "",
  "source_agent": "",
  "target_agent": "",
  "source_message_id": "",
  "content": "",
  "timestamp": "",
  "project_id": "",
  "branch": ""
}
```

---

## 36. Artifact Management

支援：

```text
diff
patch
test log
report
screenshot
jsonl
markdown
```

Artifact 不能任意讀整顆硬碟。

---

## 37. Settings

Settings 頁：

```text
Agents
Projects
Paths
Logs
Permissions
Appearance
Retention
Advanced
```

---

## 38. Agent Settings

每個 Agent：

```text
Enabled
Backend
Executable path
Default model
Default effort
Default project
Timeout
Streaming
Raw log
```

---

## 39. Permissions

Workspace 必須遵循原 Agent 權限。

不能替 Agent：

- auto approve
- bypass sandbox
- bypass filesystem restrictions
- bypass user confirmation

---

## 40. Secret Handling

Workspace 禁止寫入：

```text
auth.json
token
cookie
API key
password
```

除非使用 OS credential store。

Log 必須做 redaction。

---

## 41. Desktop Behavior

Workspace 是桌面程式。

功能：

- Desktop shortcut
- Start menu
- Remember window size
- Multi-monitor
- Fullscreen
- Always on top optional
- Minimize to taskbar

不預設 system tray 常駐。

---

## 42. Recommended Technology

Final：

```text
Tauri
React / TypeScript
Rust backend
SQLite
```

原因：

- Windows native desktop
- 輕量
- 適合三欄 persistent UI
- 能處理 local process
- 能安全管理 IPC
- 比 Electron 小

---

## 43. Alternative

如果 dot 目前已經大量使用 Python：

可以先：

```text
PySide6
```

但 Final Target 仍可遷移 Tauri。

---

## 44. Streaming

三欄必須支援 streaming。

Agent 回覆不能等完成後才整段出現。

事件：

```text
message_start
message_delta
message_end
```

Tool event：

```text
tool_start
tool_result
```

---

## 45. Stop

每個 Agent 有獨立：

```text
Stop
```

只能呼叫 adapter 的 cancel。

不能：

```text
taskkill
```

除非 backend 官方要求。

---

## 46. Global Stop

可以有：

```text
Stop Current Task
```

但要 confirmation。

只通知三個 adapter cancel。

不 kill process tree。

---

## 47. Crash Recovery

Workspace crash 後：

重新開啟應恢復：

```text
Project
Task
Sessions
Conversation
Events
```

不自動重新發送 prompt。

---

## 48. Agent Disconnect

Agent 掛掉：

Panel 顯示：

```text
Disconnected
```

並提供：

```text
Reconnect
```

不能偷偷建立新 session。

---

## 49. Offline State

如果 backend 不可用：

```text
Offline
```

History 仍可查看。

---

## 50. Unsupported Features

UI 不顯示假的功能。

例如 dot 不支援：

```text
Effort
```

就顯示：

```text
Managed by backend
```

---

## 51. Monitor Mode

保留 v0.1 Monitor。

可以切換：

```text
Workspace
Monitor
Timeline
```

Monitor Mode：

三欄只讀。

---

## 52. Workspace Mode

Workspace Mode：

可對三個 Agent 個別發送訊息。

---

## 53. Fullscreen Agent

雙擊某欄：

```text
Focus Claude
```

放大成單 Agent。

再返回三欄。

---

## 54. Compare Mode

可並排比較 Claude / dot 的兩個回覆。

```text
Compare
```

不由系統決定誰對。

---

## 55. User Notes

Task 可寫：

```text
Notes
```

Notes 不會自動傳 Agent。

除非使用者點 handoff。

---

## 56. Clipboard

可：

```text
Copy
Copy with metadata
```

---

## 57. Drag and Drop

如果 adapter 支援文件：

可拖到 panel。

Workspace 先確認：

```text
Agent supports attachments
```

---

## 58. Project Safety

切 project 時：

不可自動把未送出的 input 帶到新 project。

需要 confirmation。

---

## 59. Branch Awareness

Claude / Codex panel 顯示：

```text
Branch
Dirty
Ahead
Behind
```

如果 Git repo。

---

## 60. Git Integration

只讀優先。

可以顯示：

```text
status
diff
branch
log
```

不做：

```text
commit
push
merge
```

除非未來明確另開功能。

---

## 61. Default Collaboration Flow

Workspace 提供快捷：

```text
Claude → Dot → Codex
```

但不強迫。

使用者也能：

```text
Codex → Claude
Dot → Claude
Claude → Codex
```

---

## 62. Quick Handoff

Response 上方：

```text
Forward ▼
```

選：

```text
Claude
Dot
Codex
```

---

## 63. Handoff Preview

發送前 preview：

```text
Source:
Claude

Target:
Dot

Task:
TASK-021

Message:
...
```

---

## 64. Handoff Editing

使用者可以補充：

```text
Additional note
```

但原始 source message 必須保留。

---

## 65. Automation Boundary

Final v1：

Automatic orchestration 預設：

```text
OFF
```

Workspace 可以手動操作完整流程。

---

## 66. Future Orchestrator

未來另外做：

```text
orchestrator/
```

不能與 UI 核心混在一起。

---

## 67. Orchestrator Responsibilities

未來才負責：

```text
route
wait
retry
gate
approve logic
```

---

## 68. Workspace Responsibilities

Workspace：

```text
display
interact
record
handoff
manage session
manage project
```

---

## 69. Explicit Non-Goals

v1 不做：

- 複製三家公司所有 Desktop 私有功能
- 模型隱藏 chain-of-thought
- 破解 UI
- reverse engineer encryption
- auto deploy
- auto merge
- unrestricted filesystem
- invisible automation
- credential extraction

---

## 70. Definition of “Desktop-like”

「與 Desktop 一樣」在本專案定義為：

> 能使用 backend 真正提供的模型、effort、session、project、conversation、tool、file、stop 等能力，並在同一 UI 呈現。

不是：

> pixel-perfect 複製官方 Desktop。

---

## 71. Acceptance Test — Claude

必須證明：

- 可以建立 session
- 可以 resume
- 可以送 message
- streaming 正常
- model selector 若 backend 支援
- effort 若 backend 支援
- cwd 正確
- tool event 顯示
- stop 正常

---

## 72. Acceptance Test — Dot

必須證明：

- list / connect
- send
- receive
- thread 正確
- history
- reconnect
- unsupported capability 正確顯示

---

## 73. Acceptance Test — Codex

必須證明：

- session
- model
- effort
- cwd
- message
- streaming
- command
- stdout
- stderr
- exit code
- diff
- test
- stop

---

## 74. Acceptance Test — Handoff

Claude output：

```text
A
```

Forward to Dot。

Dot 收到內容必須保留：

```text
A
```

不可 silently rewrite。

---

## 75. Acceptance Test — Project

切換：

```text
test-repo
```

Claude/Codex cwd 必須同步。

dot metadata 同步。

---

## 76. Acceptance Test — Crash

關閉 Workspace。

重新開啟。

不能丟失：

- history
- task
- session mapping
- project

---

## 77. Acceptance Test — Security

檢查 DB / log：

不能出現：

```text
auth token
cookie
password
```

---

## 78. Acceptance Test — Unsupported Capability

若 dot 不支援 model selector：

UI 不應顯示可選 model。

---

## 79. Development Stages

dot 可以自行做到 Final，但依 Stage 執行。

### Stage 1
現有 v0.1 Monitor inventory

### Stage 2
Final architecture + adapter contract

### Stage 3
Workspace Core

### Stage 4
Claude Adapter

### Stage 5
Codex Adapter

### Stage 6
Dot Adapter

### Stage 7
Three-panel UI

### Stage 8
Session / Project

### Stage 9
Handoff

### Stage 10
Timeline / History / Search

### Stage 11
Diff / Command / Test views

### Stage 12
Crash recovery / security

### Stage 13
Final acceptance

---

## 80. Stage Rules

每個 Stage：

```text
implement
self-test
document
continue
```

不需要每個 Stage 問使用者。

---

## 81. Stop Conditions

只有以下情況停下：

- 需要管理員權限
- 需要安裝新系統軟體
- 需要更改安全設定
- 需要 token
- 需要操作正式 repo
- 需要 destructive operation
- 需要使用非公開 API 且風險未獲批准
- 無法判定正確 backend

---

## 82. Do Not Stop For

不需要因為：

- UI spacing
- local code refactor
- test fix
- internal directory naming
- minor dependency version

反覆問使用者。

---

## 83. Existing v0.1

現有 Monitor 不丟掉。

作為：

```text
Legacy Monitor Mode
```

或開發除錯 fallback。

---

## 84. Migration

現有：

```text
logs/
timeline
monitor scripts
```

應轉成新 Workspace 的 raw log source。

---

## 85. Desktop Shortcut

最終桌面：

```text
AI Collaboration Workspace
```

雙擊開啟。

---

## 86. Default Startup

啟動：

顯示上次 Project。

但不自動啟動三個 Agent。

顯示：

```text
Connect Claude
Connect Dot
Connect Codex
```

---

## 87. Connection State

每欄：

```text
Disconnected
Connecting
Connected
Busy
Error
```

---

## 88. Status Definition

Connected：

必須 backend handshake 成功。

不能只檢查 executable 存在。

---

## 89. Error Display

Agent error：

顯示原始錯誤。

例如：

```text
Codex
Sandbox setup failed
```

不只顯示：

```text
Something went wrong
```

---

## 90. Diagnostics

Settings → Diagnostics：

顯示：

```text
Executable
Version
Backend
Session
cwd
Last event
Last error
```

Secrets redact。

---

## 91. Export

Task 可 Export：

```text
Markdown
JSON
ZIP
HTML
```

---

## 92. Export Includes

- conversations
- events
- handoffs
- diff
- tests
- metadata

---

## 93. Export Excludes

- secret
- auth
- cookie
- hidden internal reasoning

---

## 94. Performance

Workspace idle：

不應持續高 CPU。

三 agent streaming：

UI 不應卡死。

大量 JSONL：

使用 incremental reader。

---

## 95. Log Rotation

避免無限長大。

設定：

```text
max size
retention days
archive
```

---

## 96. Data Location

例如：

```text
%LOCALAPPDATA%\AI-Collaboration-Workspace\
```

不要全部放桌面。

桌面只放 shortcut。

---

## 97. Portable Diagnostics

Diagnostics export：

```text
workspace-diagnostics.zip
```

不含秘密。

---

## 98. Documentation

至少：

```text
README
ARCHITECTURE
ADAPTERS
SECURITY
TROUBLESHOOTING
USER_GUIDE
```

---

## 99. Final Definition of Done

Final 版本完成，必須證明：

```text
Claude
Dot
Codex
```

三欄可以同時運作。

使用者能：

```text
選 Project
選 Session
選實際支援的 Model
選實際支援的 Effort
發訊息
看串流
看 Tool
看 Command
看 Diff
看 Test
Forward 給另一 Agent
Resume session
查看 History
```

並且：

```text
Workspace crash recovery
Logs
Timeline
No secret leakage
No forced response formatting
```

全部通過。

---

## 100. Final Product Boundary

最終產品責任：

> **提供三 Agent 的統一互動桌面，以及可追蹤的跨 Agent 協作環境。**

不負責：

> **替 Claude、dot、Codex 做決策，或模擬它們沒有提供的能力。**

---

# Execution Directive for dot

請以本 PRD 為 AI Collaboration Workspace 的最終目標規格。現有 v0.1 Monitor 視為 Stage 1 已完成。從 Stage 2 開始自行規劃、實作、測試並持續推進到 Final，不需要每個小版本詢問使用者。

不得擅自降低功能需求。任何 backend 不支援的功能，必須做 capability detection 並在 UI 正確標示，不得偽造。

只有遇到以下情況才停止請求批准：

- 管理員權限
- 安裝系統級軟體
- 安全設定變更
- 操作正式 repo
- 憑證或秘密資訊
- 新的非公開 API 風險
- 破壞性操作
- 無法判定正確 backend

最終交付需包含：

- 可執行桌面程式
- 完整原始碼
- 完整文件
- 測試
- Final Acceptance Report

