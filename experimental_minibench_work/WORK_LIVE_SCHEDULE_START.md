# MiniBench 全題型連續自動提交 V2｜2026-11-17

**正式上線已獲使用者 GO（正式授權）**。本版本由使用者核准：全部符合資格的題目依序完成，**不得因子代理呼叫失敗、模型身分未核證而停止**；不需要逐題人工批准。原加密機制維持，私人預測不得發布到公開 GitHub（程式碼平台）。

- 程式庫：`Ting-YiLin/metac-bot-template`。
- 執行分支：`experiment/work-luna-sol-minibench-20261117`。
- 狀態分支：`tingyi001-test-state`。
- 賽事：`minibench`（正式計分）。
- 不更動 `main`（主分支）、`run_live_free.yaml`（舊通道停用鎖）或其他無關排程；不得新建第二個每小時預測排程。

## 1. 模型路由：優先執行，不以身分不確定作為停工理由

1. **主控**：使用者在 ChatGPT Work（工作模式）介面選 Luna High（高思考）；完成 A（整理）、G1（資料缺口）、G2（補搜）、B（先驗）、D（反證）。
2. **最終 C 層**：每題優先嘗試實際建立 Sol 6.2 High（高思考）子代理，要求輸出最終預測、結算條款解讀、方向及反例。若取得有效輸出，即使用該結果，`forecast_author="SOL_SUBAGENT"`、`subagent_call_status="COMPLETED"`。
3. **呼叫失敗的回退**：如子代理無法建立、超時、錯誤，**不得停止整題或整輪**。由目前實際可用的主控模型獨立完成 C 層（包含完整機率／分位數與理由），記 `forecast_author="CONTROLLER_FALLBACK"`，及實際 `subagent_call_status="FAILED"/"TIMEOUT"/"UNAVAILABLE"/"UNKNOWN"`。不能在 fallback 時把主控輸出冒稱為 Sol。
4. **身分核證不足**：如 Sol 確有輸出、但缺獨立模型執行憑證，仍採用 Sol 輸出；如主控介面選定 Luna High 但環境無憑證，照常繼續。記 `model_attestation="MODEL_ID_NOT_ATTESTED"`；**不能單獨因此輸出 `BLOCKED_MODEL_ROUTING`**。若真正有獨立執行憑證才可標 `RUNTIME_RECEIPT_CONFIRMED`，並保留憑證。
5. **執行能力不足**：若某一執行端未提供 Work 專屬功能，但 GitHub 操作、可用模型及研究仍可完成，可以按上述回退流程繼續；僅當根本無法取得題目、研究、加密或提交能力時記錄具體 `BLOCKED_CAPABILITY`，不要虛報已提交。
6. **不改模型估計以迎合預覽**；不能人工選擇或替換正在開放題的機率。僅允許系統自動研究與格式校正。

V2 密封預測輸入使用既有公共欄位，`schema_version=2`。保留 `scope="MINIBENCH_WORK_LIVE_V1"`、`tournament="minibench"`、`mode="LIVE"`、`source="work_luna_sol"`、`post_id`、`question_id`、`question_type`、`reasoning`、`sources`、`research_model`、`sol_model`、`sol_effort`、`evidence_cutoff_utc`、`forecast_created_at_utc`，**另須加入**：

```json
{
  "schema_version": 2,
  "forecast_author": "SOL_SUBAGENT",
  "subagent_call_status": "COMPLETED",
  "model_attestation": "MODEL_ID_NOT_ATTESTED"
}
```

如回退，改為 `forecast_author="CONTROLLER_FALLBACK"` 與真實失敗狀態；`sol_model` 可填 `unavailable`，`sol_effort` 可填 `not_run`，`research_model` 用可確認的介面設定（如 `luna-high-ui-selected`），不要假造執行時模型 ID。V1 歷史信封仍可讀，但**新工作一律產生 V2**。

## 2. 全題型抓題與固定選題順序

1. 先讀 `tingyi001-test-state:state/minibench_work_candidate_feed.json`，檢查新鮮度、賽事、`refresh_request_id`、OPEN（仍開放）、截止時間、官方帳戶尚未投。
2. 如快照過期，依 `WORK_START.md` 的 `refresh_requests/req-*.json` 範例建立**唯一一份新的只讀刷新請求**並保存 `request_id`（請求識別碼）與 GitHub `commit_sha`（完整40碼版本雜湊）。**此時不得結束本次工作或直接宣稱 BLOCKED_REFRESH。** 立即進入下方「2A 同輪刷新橋接」，確認匹配的新題庫後，繼續研究及提交所有合格題目；不得使用過期快照或捏造資格。
3. 不以曾在聊天中出現過的題目為由排除。僅依官方賽事、未投、截止與可靠格式資料篩選。
4. 支援 `BinaryQuestion`（二元）、`MultipleChoiceQuestion`（多選）、`NumericQuestion`（數值）、`DateQuestion`（日期）、`DiscreteQuestion`（離散數值），**不得只做二元**。特殊 `ConditionalQuestion`（條件複合題）若未取得有效子題格式，僅記該題 `UNSUPPORTED_COMPLEX_TYPE`，其他題繼續。
5. 按**最早截止時間優先**、同時點按 `question_id` 升序；全部候選都要依序處理，**不限制每輪兩題**。若有3～4題或更多，能完成幾題就完成幾題；如工作環境達到實際資源／執行限制，記錄剩餘題目供下輪恢復，不把它們報為完成。
6. 每題研究前重新檢查是否已投及是否截止，防止前一題耗時造成後續資料過期。

## 2A. 同輪刷新橋接（V2.1 必經；專門修正過早 BLOCKED_REFRESH）

**已觀察的失敗機制：** 2026-11-18 澳洲時間05:42，GitHub 只讀刷新確認4題合格、可生成格式，但後續排程沒有找到對應正式提交。另一輪 Work 建立 `refresh_requests/req-*.json` 後，在 GitHub 工作流程還未開始或還未發布題庫時直接回報 `BLOCKED_REFRESH` 結束；隨後工作流程正常發布，卻沒有觸發研究與提交。這是**刷新→研究交接失敗**，不是模型提交功能失效。

1. **先檢查當前有效快照**：若已存在新鮮、範圍正確、有真實刷新收據且未過期的快照，直接用它研究；無須因為本輪沒有新的請求識別碼而再刷新。新鮮的 `items=[]` 可以是 `NO_ACTION`，舊快照的0題不可以。
2. **只在過期時發出一次刷新**：記下 `request_id`（刷新請求）、`commit_sha`（建立請求檔案的完整 Git 版本雜湊）。不要在等待期間連續產生新的刷新請求。
3. **同輪等待並核實**：優先在可執行 Python（程式語言）的 Work 運算環境讀取本檔所在的實驗分支，執行：
   `python experimental_minibench_work/refresh_bridge.py --request-id <當輪真實請求ID> --commit-sha <當輪完整40碼SHA> --wait-seconds 180 --interval-seconds 12`
   如 Work 不支援本機命令列，則以 GitHub 連接工具進行**相同的重複唯讀檢查**，先讀 `actions/runs`，找到符合 `head_sha`、`head_branch` 且 `path=.github/workflows/experimental_minibench_readonly.yml` 的該次執行，等到其 conclusion=success，再讀狀態分支題庫。應持續檢查至結果發布，不可在第一次查詢不到時就結束。
4. **四重配對**：新快照必須同時符合 `refresh_run_id`（剛完成的 GitHub 執行 ID）、`refresh_request_id`（本輪請求 ID）、`refresh_trigger=WORK_REQUEST`、`freshness_expires_utc`（未過期）以及 `tournament_requested=minibench`（正式賽）。任何一項不符均不能用該快照提交。
5. **READY（可研究）就接續下一步**：`eligible_after_status_and_deadline_check>0`（有合格題）時，**當次 Work 不得返回刷新收據當作完成，而須立即對全部候選進行 A/G1/G2/B/D/C，逐題加密→提交→官方回讀。** 若新快照確實有0題，才准回報 `NO_ACTION`（正常空批）。
6. **有上限的等待與明確故障**：預設等待最多180秒，12秒間隔；只有匹配刷新工作流程失敗、發生權限／API（介面）錯誤，或等滿180秒仍無匹配新快照，才准標 `BLOCKED_REFRESH_FAILED`／`BLOCKED_REFRESH_TIMEOUT` 並記錄 `request_id`、`commit_sha`、檢查次數、最近工作流程及未完成題目。此為真正的刷新阻擋，**不是模型失敗**；不停止既有排程。Work 實際無法持續至限額時，仍要如實標記 `BLOCKED_EXECUTION_LIMIT`，絕不可謊稱已等待。
7. **下一輪恢復**：先核對先前 `request_id`／提交 SHA 是否已有完成的刷新結果；若新快照仍有效則直接研究，不要立刻建立第二份刷新。若已過期再建立一次新的請求。不得將上一輪 `BLOCKED_REFRESH` 視為永久 NO_ACTION 或永久排除相關題目。

**不可變的保護：** 刷新橋接只做唯讀查核，不提交預測、不輸出秘密；只有完成各題研究、加密入隊和正式回讀才算成功。維持 Sol 子代理失敗→主控回退、模型未核證不中止、每題最多一次正式 POST（提交）、模糊 POST 絕不重試等 V2 安全原則。

## 3. 每題研究及官方格式契約

各題使用相同 A→G1→G2→B→D→C 研究流程，事前檢查題目結算條款，保存來源 URL（來源網址）、T0（資訊截止）與理由，格式如下：

| 題型 | 最終預測欄位 | 驗證 |
|---|---|---|
| 二元 | `p_yes` | 0.001～0.999 |
| 多選 | `option_probabilities`（選項機率字典） | 與官方選項名稱逐字匹配，總和1 |
| 數值 | `percentiles`（六個百分位數） | 轉成201點 CDF（累積分布），除非真題規格另訂 |
| 日期 | `percentiles`（帶時區日期） | 依題目日期上下界換算 CDF |
| 離散數值 | `percentiles` | 按真題 `cdf_size`（分布點數）換算，不強制201 |

六個百分位數 `p=0.1,0.2,0.4,0.6,0.8,0.9`，值非遞減；數值與日期上下界、`zero_point`（對數尺度零點）、`open_lower_bound`、`open_upper_bound`（開放邊界）一律取自當期官方題目。使用 `all_types_adapter.py` 及已鎖定的 `forecasting-tools`（預測工具套件）轉換；**不可編造答案、示例機率或用二元機率冒充其他題型**。

## 3A. V2.2 最小採證：三份私人文字檔（不改既有研究與提交流程）

**目的僅為觀察各步驟是否真的執行；不是重新設計流程。** 由 Luna 主控負責寫入、讀回、交接及記錄。每題使用單獨的**私人 Work 執行工作區**資料夾；不得在公開 GitHub 儲存庫、公開工作流程附件、狀態分支或聊天公開回報中儲存未結算機率、私人推論全文或分位數。不要為採證重新執行相同的研究／模型呼叫。

1. **A/G1/G2 後**，主控寫 `01_RESEARCH.txt`：題號、研究時間、題目結算條件、找到的2～5條關鍵來源（網址及擷取時間）、主要事實、資料缺口及補搜摘要。只記最終研究結論，不記模型內部思考過程。
2. **B/D 前**，主控**實際重新讀取** `01_RESEARCH.txt`；完成先驗及反證後寫 `02_ANALYSIS.txt`：題號、使用的研究檔名、先驗判斷依據、主要上／下修訊號及最強反例。無須重複抄錄研究全文。
3. **C 前**，主控**實際讀取** `01_RESEARCH.txt` 和 `02_ANALYSIS.txt`，以兩檔內容作為 Sol 6.2 High 子代理的工作輸入；每題都要先嘗試真實呼叫 Sol。若無法呼叫，按現有規則由主控回退，**不可省略最終預測或停止提交**。完成 C 後由主控寫 `03_FINAL.txt`：題號、兩份前置檔案是否讀取、要求的模型／思考模式、子代理實際呼叫結果及有無可查執行識別碼、最終作者（Sol 或主控回退）、結算判斷摘要，以及正式提交執行 ID／回讀狀態（取得後補記）。敏感最終機率與理由僅能存在私人工作區及既有加密通道，公開報告不顯示。
4. **主控在當輪結束前做簡短紀錄**：`01`／`02`／`03` 各自是 `WRITTEN_AND_READ`（已寫且下階段讀取）、`WRITTEN_ONLY`（只寫）、`NOT_WRITTEN`（未寫）或 `NOT_PERSISTED`（工作環境無法保留）；另記 `SOL_CALLED`／`SOL_UNAVAILABLE`／`SOL_CALL_UNKNOWN`、有無原生子代理呼叫證據。**模型自行填寫的路由文字不等於平台核證身分**。
5. **降級原則**：若 Work 沒有可保留的私人檔案空間、檔案不可讀或時間緊迫，不建立公開明文替代、不變更 GitHub 加密／正式提交程式，也不因採證失敗漏投題目。改在 Work 當輪私人結果中留下三階段的簡短摘要和缺失原因，照常完成正式提交；如無法跨排程保留私人檔案，明確報 `NOT_PERSISTED`，不得假稱下輪可讀。**本段只採證，不是新的提交門檻。**

## 4. 逐題提交：一題一收據，失敗後繼續下一題

每題完成 C 層後立即執行，**不要只研究數值題就停止**：

1. 以現有 `state/minibench_work_public_key.json`（公開金鑰）在 Work 內執行 `sealed_queue.py encrypt`，只向公開實驗分支新增 `live_pending/sealed-<hex>.json`（加密信封）；**不得上傳明文機率／理由／權杖**。
2. **一題一個 GitHub 提交版本（commit，版本提交）**，觸發 `.github/workflows/experimental_minibench_live.yml`。先等當題的 GitHub Actions（自動工作流程）完成，讀取精確對應的執行 ID／封包檔名／狀態分支 `state/minibench_live_receipts/run-<run_id>.json`，再研究及提交下一題；不因某題失敗而整批停止。
3. 每題最終以 `FORECAST_AND_PRIVATE_COMMENT_CONFIRMED`（預測與私人理由均回讀確認）判定正式成功；不能把工作流程 success（執行成功）、加密入隊或模擬測試當正式預測成功。
4. 若 `BLOCKED_ALREADY_FORECASTED_OR_UNKNOWN`、截止、`BLOCKED_FORECAST_FORMAT`、來源不足、加密失敗或提交被拒絕，記錄題號／題型／故障分類／收據，繼續下一題。
5. **不確定的 POST（寫入）絕不重試**：`FORECAST_UNCONFIRMED_NEVER_AUTO_RETRY` 或私人理由未知成功狀態，只做 GET（讀回）核對；不得自動重發相同預測。這是防止真正重複提交的必要邊界，與模型身分不確定完全不同。
6. 防重複使用官方帳戶當期已投狀態、正式提交前的 GET（讀回）與現有 GitHub Actions 併發序列；同批相同題號重複信封被程式跳過。發現其他執行輪仍在處理同題時先只讀核查，避免同題重複研究和提交。
7. 從任何中斷恢復時，優先核對現存加密隊列與持久化收據，再讀最新官方帳戶已投狀態；只接續未成功、尚未提交且不是未知 POST 的題目，不能把歷史已投題目重做。

公開回報及持久收據只能保存：`question_id`、`post_id`、題型、進行階段、`forecast_author`、`subagent_call_status`、`model_attestation`、加密檔名、工作流程 ID、提交／回讀／私人理由狀態、失敗類別和時間；**禁止未結算機率、原始分位數與私人理由出現在公開 GitHub 或聊天回報**。

## 5. 整批與長期驗收

- 單輪依序完成所有當下符合資格的題目（測試情境至少2～4題）；不得設定無依據的固定兩題上限。
- 記錄 `total_seen`（掃描題數）、`eligible`（合格）、`attempted`（嘗試）、`confirmed`（成功）、`blocked`（阻擋）、`remaining`（留待恢復）及每題耗時；成功率須以**實際官方回讀確認**計算。
- 額外分開統計 Sol 正常完成／Sol 失敗由主控回退／僅模型身分未核證；對照各組覆蓋率與後續評分，不虛報模型來源。
- 單題出錯依序紀錄並繼續；全球性認證、題庫刷新或 GitHub 權限阻擋才可結束**本輪**，保留排程，下輪再試。
- `NO_ACTION`（無合格題）是正常空批次，不能停用任何既有排程。
- 歷史成功：二元題 GitHub run `44061634254`、數值題 `44066723602`（官方201點 CDF／私人理由回讀成功）。多選、日期、離散目前仍需真題驗收。

## 6. 啟動指令

Work 使用者已設定 Luna High；啟動時直接依本文件執行一次正式多題連續研究與提交，**不得再詢問逐題授權**；不以模型自述或子代理失敗中止。完成後逐題回報收據與尚未解決問題，不公開答案機率。維持既有加密、GitHub Secrets（秘密權杖）、舊通道停用鎖及既有排程。
