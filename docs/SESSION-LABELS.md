# 可辨識的 Project / Task / Session

三欄 session 選單與目前對話列顯示：專案名稱、對話標題或已保存的第一則安全短預覽、後端、最近時間。同名專案加上足以區別的真實 repo 路徑尾段；完整路徑留在詳細資訊。Task 以任務名稱開頭，避免長路徑遮住名稱。沒有資料時明示「未知專案」「工作目錄未知」「未命名對話」「時間未知」，不猜測專案名稱。

搜尋欄只過濾本機清單，不向 backend 補讀私人對話。History 可跨專案查看已保存的 session 與對話；選取不會連線或 Resume。原有 Task History 仍可從主畫面 History 模式或 session 歷史的 Task History 按鈕查看。

Session ID 保留於 item data、tooltip 與「詳細 / ID」，可按 Copy session ID 複製。所有選取、重新排序、匯入、Resume 與 handoff mapping 仍使用原始 ID，從不反查顯示標籤。長中文標題縮短顯示；完整 repo 路徑與 ID 在詳細資訊保留。Resume 選到不同工作目錄時會拒絕：先切到該專案與任務，再 Resume；不會在目前 repo 恢復舊 session。

原始 DB 無需遷移。過去以 ID 當 title 的紀錄僅在顯示時忽略；已有官方 session metadata 的 firstPrompt、directory 與更新時間會保留於新匯入紀錄。不讀 auth、token、cookie 或隱藏推理；不呼叫 Claude／Dot／Codex 補資料。

可見隔離驗收：`scripts/run_session_labels_ui.py`；證據位於 `evidence/session-labels-ui/`。使用明確標記的測試替身與獨立目錄；不代表新的 live backend 驗收。更新已安裝 Python 原始碼時備份與核對 SHA256；不關閉已開啟的使用者視窗，不改 EXE、防毒或正式 repo。既有視窗需在使用者保存草稿並自行關閉後重新開啟，才會載入新程式碼。
