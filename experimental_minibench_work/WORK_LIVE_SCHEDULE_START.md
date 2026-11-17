# MiniBench 全自主正式計分啟動規格｜2026-11-17

**使用者已明確給予 GO（正式上線授權），不再需要逐題人工核准。**

執行分支：`experiment/work-luna-sol-minibench-20261117`。狀態分支：`tingyi001-test-state`。正式賽：`minibench`。本方案保留 `main`（主分支）、舊排程、`run_live_free.yaml` 原停用鎖不動。

## 一、排程與模型

每小時由 ChatGPT Work（工作模式）主控執行一次，使用由使用者配置的 Luna High（高思考）做 A 摘要、G1 缺口、G2 補搜、B 先驗與 D 反證。每一題的 C（最終預測）**實際建立** Sol 6.1 High（高思考）子代理，讓其獨立質疑 Luna 並輸出 p_yes（事件成立機率）及理由。

**不能用模型名稱欄位冒充真實模型呼叫。** 當前排程若不是 Work、不能建立指定模型的子代理，則本輪 `BLOCKED_MODEL_ROUTING`，不可改用未經授權的其他模型直接提交。模型、思考模式由 Work 任務介面設定，不在程式中自動切換。

## 二、題庫刷新及避免人工介入

1. 讀取 `tingyi001-test-state:state/minibench_work_candidate_feed.json`。驗證正式賽識別碼、刷新時間、效期、模型可用性及 OPEN／未投狀態。
2. 快照過期或無來源收據時：根據 `experimental_minibench_work/WORK_START.md` 的格式，於實驗分支建立全新 `refresh_requests/req-*.json`，在相同執行回合讀回配對的 `refresh_request_id`。若未匹配，`BLOCKED_REFRESH`，不可使用舊快照。
3. 只挑選 `BinaryQuestion`（二元題），以截止時間排序，逐題做自動研究。其他類型標記 `UNSUPPORTED_TYPE`，不把二元機率套到數值、日期或多選題。
4. 不能人工預覽正在比賽的預測後重新挑題或調整機率。歷史上已在聊天視窗展示給使用者的 Q46608／46868 不得送入本次正式計分隊列。
5. 沒有題目是 `NO_ACTION`，不代表排程應取消、暫停或停止；僅結束當次執行。

## 三、加密正式隊列（不可公佈機率或理由）

**公開 GitHub 儲存庫只能提交加密預測。** 從狀態分支讀取 `state/minibench_work_public_key.json`（公鑰），確認 `scope=MINIBENCH_WORK_FORECAST_ENCRYPTION_ONLY`；若不存在或版本不符，阻擋，不得將明文預測提交到 GitHub。

每題完成後，在 Work 私有運算環境中準備以下明文結構（不要貼到公開 repo）：

```json
{
  "schema_version":1,"scope":"MINIBENCH_WORK_LIVE_V1",
  "tournament":"minibench","mode":"LIVE","source":"work_luna_sol",
  "question_type":"BinaryQuestion",
  "post_id":1234,"question_id":5678,"p_yes":0.321,
  "reasoning":"C 層最終判斷與結算依據，至少50字元。",
  "sources":["https://example.org/actual-official-source"],
  "sol_model":"gpt-6.1-sol","sol_effort":"high","research_model":"luna-high",
  "evidence_cutoff_utc":"YYYY-MM-DDTHH:MM:SSZ",
  "forecast_created_at_utc":"YYYY-MM-DDTHH:MM:SSZ"
}
```

僅把真實研究內容代入上述格式；`example.org`及範例題號不可直接使用。時間必須由當次執行實際記錄。

在 Work 的臨時運算環境中執行 `sealed_queue.py` 的 `encrypt` 指令（需 `cryptography` Python 套件），以公鑰加密成保密封包：

`python sealed_queue.py encrypt --public public_key.json --input forecast_private.json --output sealed.json`

再透過 GitHub 連接工具，在實驗分支**只建立**新檔：

`experimental_minibench_work/live_pending/sealed-<12至40碼小寫十六進位識別字>.json`

檔案內容必須是加密 envelope（封包），包括 `version,key_id,ephemeral_pub,nonce,ciphertext` 五欄；**不得提交明文 p_yes、reasoning、來源或私有密鑰**。研究原始資料留在 Work 內，不要寫入公開 Repo。

## 四、正式提交通道

這項新檔案會觸發 `.github/workflows/experimental_minibench_live.yml`（正式計分提交工作流程）。由 GitHub Actions 透過既有 `METACULUS_TOKEN` 解密，重新查核真正的當期題目與帳戶已投狀態，驗證時間／機率／來源；正式只支援二元題。

每題最多一次 POST（提交），再以 API GET（讀取）驗證**機率值精確匹配**。確認預測後，使用官方私有留言 API 發送分析理由 `is_private=true`，再嘗試讀回留言。所有未知 POST 結果絕不自動重投；只讀回或待人工稽核，不可造成重複。

正式賽成功只能回報 `FORECAST_AND_PRIVATE_COMMENT_CONFIRMED`；若預測已確認但留言未確認，必須標 `FORECAST_CONFIRMED_COMMENT_UNCONFIRMED_NO_AUTO_RETRY`。API timeout 且預測未確認時標 `FORECAST_UNCONFIRMED_NEVER_AUTO_RETRY`。

## 五、每次執行最小紀錄

Work：觸發時間／刷新請求識別碼／題目ID／截止時間／模型實際呼叫收據／加密隊列檔名／研究快照時間／是否成功進隊列。

GitHub Actions：執行 run_id、版本 commit、單次 POST 嘗試、平台讀回是否匹配、私人留言是否讀回、失效分類；公開紀錄**不得顯示尚未結算之原始機率與理由**。加密原始隊列保留供後續稽核與結算後分析。

## 六、重要現況與限制

- 正式計分工作流程的「**空批次不提交**」與加密單元測試已通過；目前**尚無真正加密 Sol 預測入隊列及正式賽 POST 收據**。
- Work 是否可以透過目前的「ChatGPT 排程」自動啟動並保留主控 Luna High／子代理 Sol 6.1 High 設定，需由排程實際執行收據驗證。不能因排程成功建立就宣稱已經跑了 Work。
- MiniBench 官方要求全自主、不得由人工預覽開放賽題預測後作針對性改動；新題不透過人工逐題裁決。
- 競賽帳戶是否已完成必填參與表單尚未獨立核查，不得宣稱已具獲獎資格。
- 其他題型下一版再擴充，不影響二元題先行正式上線。
