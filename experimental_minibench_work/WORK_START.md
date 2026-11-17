# Work（工作模式）MiniBench 新架構：端到端不提交測試

正式賽實驗分支：`experiment/work-luna-sol-minibench-20261117`  
狀態分支：`tingyi001-test-state`  
正式競賽：`minibench`。主分支、原排程、`run_live_free.yaml` 不得修改；正式計分預測不准提交。

## 核心模型分工

本 Work 主控由使用者選定 Luna High（高思考），負責 A 摘要、G1 缺口分析、G2 補搜、B 先驗及 D 反證。
C（最終機率判斷）須實際啟動 Sol 6.1 High（高思考）子代理；不可用名稱標籤假裝已啟動。Sol 可以質疑前段研究並補搜。E（程式查驗）完全不呼叫提交 API。

## 第一階段：取得當次、非過期題庫

1. 以 GitHub 連接功能讀取 `tingyi001-test-state:state/minibench_work_candidate_feed.json`。
2. 確認 `tournament_requested=minibench`、`scope=AUTHENTICATED_OPEN_SLICE_ONLY_READ_ONLY_NO_SUBMISSION`、`refresh_run_id` 存在、`checked_at_utc` 與 `freshness_expires_utc` 有效、`truncated=false`。
3. 若過期，由 Work 在**實驗分支**新建一個檔案：
   `experimental_minibench_work/refresh_requests/req-YYYYMMDDTHHMMSSZ-xxxxxxxx.json`，其中時間是實際當前 UTC（世界協調時間），xxxxxxxx 為新的6至16碼小寫英數識別字。
   檔案內容（所有時間與識別碼須真實替換）：
   ```json
   {
     "schema_version":1,
     "request_id":"req-YYYYMMDDTHHMMSSZ-xxxxxxxx",
     "source":"chatgpt_work_scheduled_forecast",
     "tournament":"minibench",
     "intent":"READ_ONLY_REFRESH",
     "created_at_utc":"YYYY-MM-DDTHH:MM:SSZ"
   }
   ```
4. 只讀檢查最新刷新執行是否完成，再讀取狀態分支同一檔案，要求 `refresh_request_id` 精確等於這次請求 ID，且 `refresh_trigger=WORK_REQUEST`、`refresh_run_id` 非空、資料未逾期。沒有配對資料時本輪 `BLOCKED_REFRESH`，不可使用舊題庫假裝刷新成功。
5. 若確認0題則 `NO_ACTION`；僅接受 `BinaryQuestion`（二元題）進入下一階段，非二元題記錄 `UNSUPPORTED_TYPE`。

## 第二階段：真實模型研究

對符合條件且未接近截止的1題優先完成 A、G1、G2、B、D、C。採用最新可查證來源，保存決策重要證據網址與擷取時間。不能將社群機率誤稱為獨立歷史基準率；不能忽略正式結算的實際觸發條件。Sol C 必須回答：YES（事件成立）機率、最主要理由、最強反證、條款判定與時間邊界。

## 第三階段：工作結果送入隔離 GitHub 隊列（不提交）

每題在實驗分支建立獨立新檔：
`experimental_minibench_work/pending/q-{post_id}-{question_id}-{unique}.json`

```json
{
  "schema_version":1,
  "scope":"MINIBENCH_WORK_DRY_RUN",
  "tournament":"minibench",
  "mode":"DRY_RUN",
  "source":"work_luna_sol",
  "post_id":1234,
  "question_id":5678,
  "p_yes":0.123,
  "reasoning":"Brief but substantive independent rationale with resolution verification.",
  "sources":["https://example.org/primary-evidence"],
  "evidence_cutoff_utc":"YYYY-MM-DDTHH:MM:SSZ",
  "forecast_created_at_utc":"YYYY-MM-DDTHH:MM:SSZ"
}
```

上例為格式說明；必須替換真實題號、機率、網址及時間，**不可將範例送入真實隊列**。
機率界限0.001至0.999、理由20至7000字元、兩時間均須 UTC；模型不能查看官方答案或原預測，不能把已結算題送入。

GitHub 推送新檔後，`experimental_minibench_queue.yml` 只以既有平台權杖重新讀取當期開放題，檢查題號、題型、截止與重複狀態，**絕不 POST（提交）**。檢查工作成功不等於題目通過；必須閱讀其 `minibench_work_queue_receipt.json`，確認該題是 `PASS_DRY_RUN`，不是 `BLOCKED`。

## 完成時輸出

回報：實際研究題號、研究來源、Sol 子代理證明及 C 機率、隊列檔案連結、GitHub run ID、正式平台是否有提交（必須為否）、是否 PASS_DRY_RUN、受阻原因。不得把不提交測試或工作流程成功宣稱為正式計分預測成功。

**正式賽 GO／NO-GO（上線／不上線）仍為 NO-GO，直到使用者另外核可。** 正式提交時另須依官方規則補上私人理由留言、成功回讀及非二元題型處理。
