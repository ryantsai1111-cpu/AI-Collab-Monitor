# AI Collaboration Workspace：完整來源＋Windows x64 Qt 候選版

> 歷史文件（2026-10-09 標註）：保留原始交付／驗收內容。啟動與現況以 [文件索引](../README.md)、[使用指南](../USER_GUIDE.md) 及 [目前測試紀錄](../../tests/README.md) 為準；文內舊計數、路徑或操作授權不能直接套用本版。部分 evidence 未隨此 checkout 提供。

此包包含完整程式來源與官方 PySide6 6.11.2 的 Windows x64 相依檔案。解壓縮後同一個根目錄即有 run.py、requirements.txt、acw/、vendor/、tools/、docs/ 和 tests/，不需把兩個變更包手動拼接，也不需複製原安裝的 vendor。

這不是含 Python 的獨立 EXE。仍需已存在且目前確認可用的相容 Python；Windows 啟動、原生 DLL 載入與真實 Agent 連線尚未驗證，Final 未認證。

## 解壓縮位置

請使用新的資料夾，例如：

C:\Users\ryant\Downloads\ai-collab-workspace-with-qt-candidate

不要覆蓋你先前的 C:\Users\ryant\Downloads\ai-collab-workspace-full-source-candidate、原安裝或工作資料。若上述新資料夾已存在，先選擇另一個空白資料夾；本包不會自動合併或取代舊資料。

解壓縮後確認該資料夾根目錄有 run.py，且 vendor/ 是它的同層資料夾。請完整保留 vendor/ 的 DLL、PYD、Qt plugins、Shiboken、metadata 和 license，不要自行刪減。

## Python 條件與標準入口

- Windows x64，標準、非 free-threaded 的 CPython 3.11–3.14；先前使用的 3.12 是適合的目標，但它目前仍未核實
- 本包不是 32-bit、原生 ARM64 或 PyPy 相依環境
- 官方 Qt 6.11 平台表列出 Windows 10 1809+ 與 Windows 11
- Python 3.10 另需 tomli；本包針對 3.12，不支援用缺少該額外相依檔的 3.10 直接執行
- 不需要假設系統全域已有 PySide6。既有 run.py 會優先從本包同層 vendor/ 載入 Qt

你提供的舊 python-path.txt 記錄：

C:\Users\ryant\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\pythonw.exe

此路徑只是歷史設定，當前存在性、版本與架構未確認。不要在它不存在或不相容時強制使用，也不要推定有 python.exe 同層檔。可以使用任何已確認相容的既有 Python，不需綁定 Codex runtime。

確認所選 Python 相容後，普通的開發入口是：

"<已驗證的 Python 路徑>" "C:\Users\ryant\Downloads\ai-collab-workspace-with-qt-candidate\run.py" --data-dir "C:\Users\ryant\Downloads\ai-collab-workspace-with-qt-candidate\ui-review-data"

請先使用新的隔離資料。不要假設雙擊 run.py 的檔案關聯正確。此標準 Python 入口不是避開 Windows 安全檢查的承諾。

## 安全與角色行為

- 沒有 BAT／CMD／PS1／捷徑或自製 EXE 啟動器
- vendor/ 保留官方 wheel 內的 Qt 工具 EXE，沒有將它們用作 Workspace 啟動器，也沒有執行
- 不需關閉或變更 Windows 安全設定；若遭攔截，停下並保留訊息，不要重新命名、解除封鎖、移除來源標記或加防毒排除
- 不讀取、複製先前被拒絕的舊 vendor 路徑，也不以本包規避對特定程式的偵測
- 啟動只開啟本機工作區；不自動連線、恢復 Agent 對話、重送提示、批准工具或交接
- Claude 主審、G8毛 轉接／複核、Codex 實作的角色與 G8毛 每次手動同意規則不變

## 來源、完整性與授權

程式來源基準 b58c1760a56a003cd78e627541137dc135d671a0，搭配已獨立審查的 UI。其他來源／歷史文件保留原內容；啟動以本 README 為準。

四個官方 PyPI Windows x64 wheels：PySide6、PySide6_Essentials、PySide6_Addons、shiboken6，全部固定 6.11.2。下載 SHA-256、RECORD、解壓後檔案 hash 與 ZIP CRC 已核對。完整保留 3,795 個唯一檔案；跨 wheel 同名內容皆一致，沒有不明覆寫或刪減。

所有 wheel 原附 metadata／license／notice 均保留。METADATA 的 License 欄列 LGPL-3.0-only OR GPL-2.0-only OR GPL-3.0-only，原附檔案含 LicenseRef-Qt-Commercial.txt。本包是供同一使用者既有 app 的私人使用準備，沒有代替使用者作法律適用判定。Qt 說明：https://www.qt.io/development/open-source-lgpl-obligations ；第三方授權：https://doc.qt.io/qtforpython-6/licenses.html

來源／wheel SHA、逐檔清單及驗證界限見 COMPLETE-MANIFEST.json 和 evidence/qt-dependencies/。

## 實測界限

- 同一份來源在雲端 Linux／Qt／100% 畫面下透過原有 run.py 啟動成功，85 個新離線測試通過（67 UI＋18合約）
- 該實測使用雲端 Linux Qt；本包新增的 Windows Qt 僅做靜態 archive／hash／ABI／PE／layout 驗證，沒有執行 Windows DLL、PYD、EXE 或安裝 hook
- 歷史 tests.zip 未取得有效二進位內容，不能宣稱原完整測試套件通過
- Windows 實體螢幕、Narrator、真實輸入法、既有 Python 狀態、啟動安全限制、原生 SDK 與真實 Agent 操作仍未驗證
- 沒有新系統安裝、全域 PATH 或安全設定修改，沒有工作資料、認證、原始日誌或歷史診斷
- 遠端 GitHub 發佈仍暫停
