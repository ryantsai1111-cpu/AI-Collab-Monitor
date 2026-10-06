# dot 驗收 — 待測（Claude 沒有直接呼叫 dot 的工具，未代測）

狀態：**待測**。CLI 通過也不代表 dot 已恢復。

## 交辦文字（貼給 dot）

> 請透過你自己的 Ryan-PC 連線，只執行一次下列唯讀命令，不要重試、不要安裝或修改任何東西：
>
> ```powershell
> [pscustomobject]@{ Computer = $env:COMPUTERNAME; User = (whoami); Time = (Get-Date -Format o) } | Format-List
> ```
>
> 回報：命令的原始輸出與結束碼。
> 若命令未啟動，回報完整原始錯誤（包含 `exec-server rejected request` 的代碼與訊息）後停止。

## 通過標準

- 輸出 Computer = `RYAN-PC`、User = `ryan-pc\ryant`、Time 為執行當下時間
- 無 `helper_unknown_error: setup refresh had errors`
- `C:\Users\ryant\.codex\.sandbox\sandbox.<當日>.log` 對應時段沒有新的 `setup refresh had errors`
