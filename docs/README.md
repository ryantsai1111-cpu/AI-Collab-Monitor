# 文件索引

更新日期：2026-10-11。以目前 checkout 的程式與測試確認現況；舊報告的計數、機器路徑與授權只代表當時的驗收，不是新操作指令。

## 現況與操作

| 文件 | 用途 |
| --- | --- |
| [根目錄 README](../README.md) | 啟動、功能摘要與維護指令 |
| [USER_GUIDE](USER_GUIDE.md) | 目前 UI 操作 |
| [TROUBLESHOOTING](TROUBLESHOOTING.md) | 啟動、CLI 更新、session 與協作排查 |
| [ARCHITECTURE](ARCHITECTURE.md) | instance／provider、儲存與恢復 |
| [ADAPTERS](ADAPTERS.md) | 後端介面；其中原生版本與 live 報告是歷史證據 |
| [HERMES](HERMES.md) | 原 Local LLM 改接 Hermes：操作、協定、session 與核准邊界 |
| [AGENT-CONTEXTS](AGENT-CONTEXTS.md) | 各 Agent 獨立 project／task／session |
| [SECURITY](SECURITY.md) | 核准、資料保存、檔案及 credential 邊界 |
| [SESSION-LABELS](SESSION-LABELS.md) | 本機 session 標籤與來源 |
| [DOT-UNOFFICIAL](DOT-UNOFFICIAL.md)、[DOT-CONVERSATION](DOT-CONVERSATION.md) | G8毛 整合與後續修訂；新段落優先於早期手動模式描述 |
| [測試 README](../tests/README.md) | 當前離線結果、已知失敗與歷史基準 |
| [scripts README](../scripts/README.md) | 維護入口、runtime helper 及歷史腳本 |

## 設計與後續工作

- [UI-REFRESH](UI-REFRESH.md)：最上方是已確認產品方向和現況差距；下方保留舊 UI 設計。
- [DESIGN-auto-collab](DESIGN-auto-collab.md)：協作規則及現有能力。
- [LANDSCAPE](LANDSCAPE.md)、[GITHUB-DOT-RESEARCH](GITHUB-DOT-RESEARCH.md)：調研當時的比較，不代表外部專案現況或本機驗證。
- [PRD](PRD.md)：原始需求基準，保留原文；固定三角色等舊方向已有後續使用者決策，不能當成目前能力清單。

## 歷史交付與驗收

以下保留追溯，不作為目前啟動指令或測試總結：

- [BASELINE-README](BASELINE-README.md)、[CANDIDATE-PACKAGE-README](archive/CANDIDATE-PACKAGE-README.md)：舊安裝／分包。
- [REQUIREMENTS](REQUIREMENTS.md)、[CONTINUATION-NOTES](archive/CONTINUATION-NOTES.md)：舊驗收 ledger 與接續紀錄。
- [EXE-SOURCE-HARDENING](EXE-SOURCE-HARDENING.md)：舊 EXE／installer 審查；目前 checkout 沒有 install.ps1。
- [HANDOFF-local-llm-panel](archive/HANDOFF-local-llm-panel.md)、[LOCAL-LLM-DELIVERY](LOCAL-LLM-DELIVERY.md)：Local 初次規格與交付；固定四角色限制已由自由新增 Agent 決策取代。
- [HANDOFF-SAFETY-2026-10-07](archive/HANDOFF-SAFETY-2026-10-07.md)、[BACKEND-RELIABILITY-2026-10-07](archive/BACKEND-RELIABILITY-2026-10-07.md)、[DOT-CONVERSATION-ACCEPTANCE](DOT-CONVERSATION-ACCEPTANCE.md)：指定日期與範圍的驗收。

歷史文件可能引用未隨這份 checkout 提供的 evidence。缺少原始證據時，不將歷史 PASS 升格成本版驗收，也不補造檔案。舊版本紀錄的機器操作指示不授權再次登入、部署、傳訊或清理資料。
