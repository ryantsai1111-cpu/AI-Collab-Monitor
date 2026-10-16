# 角色腳本（playbook）

每個 Agent instance 各有一份角色腳本。在工作區「⋯ → 角色腳本…」或側欄標頭旁的「角色腳本」編輯，預設選取目前 Agent。動態 instance 沿用 provider 的預設，再各自儲存。切換 Agent 若有未儲存修改，會詢問先儲存、捨棄或取消切換；還原預設前另有確認，預設不還原。編輯欄位按 Enter 不會觸發任何對話框按鈕。

| 欄位 | 用途 |
| --- | --- |
| role | 卡片與側欄的短標題，最多 40 字 |
| duties | 給人看的職責 Markdown |
| instructions | 派工提示的前綴 Markdown |
| limits | run_budget／max_turns 只作為 Hermes 請求未提供該欄位時的預設；timeout_seconds 只對 Codex 生效，皆為正整數 |
| permissions | commit、push、outside_card 布林角色約定 |
| report | 給人看的回報格式 Markdown |

三個 Markdown 欄位各最多 20000 字。limits 上限為 Qt 編輯器的 2147483647；dispatcher 仍套用自身執行預算與回合的上限。權限是角色約定，不授予外部工具權限；實際操作依原始任務與後端核准。只有 instructions 會自動加入提示；需要強制提醒的回報要求應同時寫在 instructions。

資料存在 Workspace 設定 `playbook.<agent_id>`。缺少欄位會補 provider 預設。按「儲存」或「還原預設」後，會以暫存檔與 os.replace 更新 `data_dir/playbooks/<agent_id>.md`，供 skill 等外部程式唯讀；未儲存的預設可由 GUI 載入，但不會在啟動時寫檔。這份 Markdown 是設定的投影，編輯它不會回寫 GUI。

請求檔派工（Hermes 與 Codex）預設將 instructions 放在原始 prompt 前，以 `---` 分隔；`use_playbook: false` 可明確停用。自動協作每一步也套用該 instance 的 instructions，既有 VERDICT 與 ACW_REPLY/ACW_END 信封保持原樣。一般手動對話不會自動加入 playbook。完整請求格式與通用 CLI 見 [HERMES.md](HERMES.md)。

設定內容損壞時，load 會回 provider 預設並記錄一次 warning，避免每次 UI 刷新重複刷屏；不會自動覆寫壞設定。明確儲存時先更新設定，再原子更新 Markdown 投影。
