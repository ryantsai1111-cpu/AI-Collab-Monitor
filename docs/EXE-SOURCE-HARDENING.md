# EXE source hardening — approval boundaries

G8二審批准 A–F 的 source-only 修正。原 source 的逐檔備份／SHA 在 `evidence/exe-source-hardening/original-source/`、`baseline.json`；Claude 原提案保持原樣。

Launcher：未知／多餘參數拒絕，不會靜默回落到正式 data。只接受無參數或 `--data-dir` 絕對路徑。全 Main 錯誤處理，檢查已配置 Python 的絕對路徑、檔名、存在與 run.py。檔名／path/hash 不等於 publisher/PE identity 完整驗證。Windows quoting 使用兩個 .NET regex；離線測試取實際 C# 常數，以可信 PowerShell 的 .NET Regex 執行，再用 Windows CommandLineToArgvW 作獨立 oracle；**沒有編譯／執行 C#**。Process.Start／兩秒非零早退檢查不證明 UI ready。版本與 asInvoker manifest 僅供追溯。

Installer：`install.ps1` 預設只輸出 read-only preflight plan，需明確 Destination、ExpectedResolvedDestination、ExpectedUserProfile、BuildManifest。本輪連 plan entry script 也沒有執行；測的是 `installer_policy.py` 真正純 policy 與已授權的 mock。既有 app、legacy manifest、completed-but-EXE-missing、任何 partial state 全部 fail closed，不自動 resume／補回可能隔離檔。來源 allowlist 僅 runtime 程式／bundled dependency／指定三份使用文件／bounded Dot runtime entry，排除 tests、evidence、一般 scripts、auth/config secrets；symlink dependency 必須另作經審查的 flattening 決策，不自動處理。全部 source/hash/shortcut/profile/alias 檢查在第一個寫入前。未部署、遷移或修改現有 shortcut/data。

Build：新增 `build_launcher.ps1` source，預設只 plan；`-Execute` **不是本次批准**。未執行此 script 或 compiler。未來僅使用既有 Valid-signature compiler，輸出到新的隔離 tests 子目錄，不覆寫舊 binary、不重試、完整記錄 sources/compiler/output hash、argv、stdout/stderr/signature/status。Determinism 標 `NOT_VERIFIED`，publisher trust 不成立。產出的 manifest 只是 provenance，不是 malware verdict。

Launch verifier：新增明確 target 與 expected physical path，比對 build hash；shortcut sandbox COM 的 resolution 未確立時拒絕自動測 shortcut，仍列為待人工-context 驗收，不降低 PRD。明確 -Execute 與新批准前不啟動 EXE。Win32 NativeErrorCode/HResult/原錯誤保留；拒絕為 BLOCKED、不重試。data scope 根據 owned child 的實際 argv；backend 狀態根據隔離 DB 的 state evidence，缺資料為 UNKNOWN。只有 scoped window/start/close 結論，不能替代 backend、AV 或 Final。

測試入口 `scripts/run_exe_source_tests.py`：隔離 fixtures／mock、純函式、可信 PowerShell AST parser/pure helpers、OS 記憶體 argv parser。不得呼叫 build／install／launch entry scripts、csc、未知 assembly、應用程式 EXE。C# 本體與實際 deployment 仍未驗證。

Rollback：原 source 可逐檔比對／回復備份；新 source 可保留或經審查移除。此輪不刪除／還原／覆寫任何 binary、shortcut 或 data。部署遷移、工具安裝、签署、vendor upload、安全設定、編譯或 EXE 執行均由主對話另行決定；不自動批准。

## B1–B3 source-only remediation (second draft)

第一稿備份在 `evidence/exe-source-remediation2/first-draft-source/`，逐檔hash在同目錄 `baseline.json`。第一輪 `exe-source-hardening` 的original-source、12-case結果及Claude複審保持原樣。本輪Launcher.cs不變、不更新installed app，不編譯或執行EXE。

Planner先以lstat檢查根目錄、父目錄、每個子目錄／檔案的symlink與Windows FILE_ATTRIBUTE_REPARSE_POINT；所有junction／reparse tag拒絕，不讀target、不flatten。完整eligible-source inventory與manifest逐項對照；不是「有一個前綴就完整」。每個排除項記path、reason、necessity及content_read=false。Python cache可明確列GENERATED；credential-like names與其他未知資源不讀內容，必要性UNKNOWN便拒絕部署。

本地只讀metadata已看到：acw目前有Python檔／adapter目錄／cache；Dot package有Python檔／cache；vendor根目錄有PySide6、shiboken6及其dist-info，另有bin目錄；SDK node_modules有.pnpm、.bin、package-manager metadata及@anthropic-ai。`@anthropic-ai/claude-agent-sdk`實際是junction。vendor/PySide6內部讀取遭拒，未升权或重試；其完整資源／metadata清單未驗證。Planner現在會列舉vendor根目錄、保留已識別PySide6/shiboken6的dist-info，而不是漏掉metadata；未知vendor/bin、其他套件／非Python自有資源需個別審查，不能當作可省略。實際依賴準備及完整runtime驗收仍未執行；目前layout可能且應當被fail-closed拒絕。

必要入口另依應用實際imports要求PySide6 QtCore/QtGui/QtWidgets及Shiboken原生模組、distribution METADATA；SDK entrypoints由已列舉且非連結的pinned package.json exports/main宣告取出並與完整inventory對照。版本不符、缺入口、wildcard／未知metadata格式全部拒絕。這些是將來部署的必要性檢查，不表示本輪已讀到／核對vendor內部所有檔案，也不證明所有transitive dependencies可執行。

Package診斷source新增可信kernel32 GetCurrentPackageFullName API，與resolve／expected alias一致性同時使用。PACKAGED、UNKNOWN、alias未知／不同或physical LocalCache判定均拒絕。純測試只mock return codes；現有probe曾觀察LocalCache resolved path，但不是新planner實機測試。UNPACKAGED也不證明不存在任何filesystem filter／virtualization，不能將此診斷當作完整安全邊界。

Launch observer以bounded ASCII-escaped JSON stdin傳CommandLine，避免內嵌引號作native argv。DB仍為acw實際的workspace.sqlite3及既有events schema。SQLite／JSON錯誤保留component、error_type與原message，結論UNKNOWN；不能產生假的backend=false。`data_dir_argument_isolated`只證明argv，`prod_data_used`保持UNKNOWN。正常關閉在finally，只限已由實際argv確認且PID、creation time及CommandLine仍一致的owned程序；辨識不足／WMI拒絕只記UNKNOWN，不kill、不碰其他視窗。Preflight未執行則BLOCKED_PREFLIGHT；scope PASS仍不證明正式資料無存取、backend／防毒／Final驗收。

機器JSON用ASCII escaping；planner輸出／輸入及PS ConvertFrom-Json前有1000000-character限制，超過即拒絕，沒有分段繞過。巨大diagnostics會明列truncated=true，而不是當作完整inventory。Build source加入/noconfig及explicit System.dll reference，標attempt在Process.Start前；stdout/stderr由redirected streams同時非同步讀取，保留exit/native failure。仍未呼叫csc，沒有compiler/runtime能力驗證或新的binary。

## Human-reviewed INCOMPLETE rollback plan (not executed)

INCOMPLETE或既有app一律不自動resume。未來需另行批准清理前，先保存install-manifest及核對其logical/resolved app path、recorded created_shortcuts和每個來源hash；若沒有manifest、alias／profile不一致或reparse，停止人工審查。只考慮manifest明確記錄且TargetPath可在預定人類context證實指向該app的shortcut，與明確app目錄。兄弟 `data`、使用者指定的data-dir、正式repo、既有EXE／隔離區都不在此計畫的可自動操作範圍。先確認沒有使用中的本程式，列出具體影響路徑供人類批准；本輪只提供計畫，沒有刪除、移動、還原或清理命令。沒有manifest不能猜測可以刪哪些檔案。
