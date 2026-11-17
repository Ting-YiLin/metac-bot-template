# MiniBench 五題型擴充：工程驗收與問題紀錄

日期：2026-11-17。使用者正式裁決：優先全面打通所有題型，遇到局部錯誤記錄並持續改善；不得因假設性風險擅自放棄題目。

## 範圍和架構

不更換 Luna High（研究主控）→ Sol 6.1 High（最終判斷）→ GitHub Actions（正式提交）與公鑰加密隊列。
原先正式二元題 API 已於 2026-11-17 真實提交並回讀確認（run 44061634254）。
此次增加：
- `MultipleChoiceQuestion`：逐選項機率映射，總和為1，選項名稱與官方完全一致。
- `NumericQuestion`：模型輸出六個分位數（10／20／40／60／80／90），按官方 SDK 生成 CDF（累積分布）。
- `DateQuestion`：帶時區的 ISO 日期分位數，按真題上下界轉為 CDF。
- `DiscreteQuestion`：分位數轉換為依 `cdf_size` 動態長度 CDF，而非假設201點。
- 原 `BinaryQuestion`：保留現有一次性提交、防重複與私人理由留言。

實作路徑：
- `experimental_minibench_work/all_types_adapter.py`
- `experimental_minibench_work/live_submit.py`
- `experimental_minibench_work/minibench_readonly_probe.py`
- `experimental_minibench_work/WORK_LIVE_SCHEDULE_START.md`

研究端新契約：每題依 `format_context`（選項、範圍、開放邊界、CDF 點數）要求 Sol 產生適當輸出。不可用二元機率假冒其他格式；缺少資料只阻擋當題。

## 驗證證據

- [全格式離線套件 run 44064726113](https://github.com/Ting-YiLin/metac-bot-template/actions/runs/44064726113)：81項測試通過（當時版本），涵蓋五型轉換、四類非二元 POST（模擬）、私人留言回讀及原版相容。
- [正式提交工作流程 run 44064628366](https://github.com/Ting-YiLin/metac-bot-template/actions/runs/44064628366)：新增四型獨立測試成功；這次是**空批次**，沒有真的送出非二元正式賽預測。
- 真實題庫只讀 run 44064726042：API OPEN 切片3筆，合格未投2筆，包含二元1題、其他支援題型1題；發布了含格式上下文的快照。
- 公開版每次正式提交流程的摘要收據可保存至隔離 `tingyi001-test-state:state/minibench_live_receipts/run-<run_id>.json`，不保留未結算機率、私人理由或完整分布。run 44064628366 已實際發布收據。
- 定時「MiniBench Luna／Sol 自動預測」已修改為五題型自動路由；原排程保持啟用，不新建重複任務。每日監控已修改為分題型統計。

## 開發期間發現並修復

| 問題 | 根因 | 修正 |
|---|---|---|
| 統一回讀導致二元測試失敗 | 仍將純量傳給需要向量的共通回讀函式 | 改為完整預期機率向量 |
| 兩個格式測試錯誤 | 精確浮點數比較不適合概率歸一化 | 改為浮點容差比較 |
| 群組題回讀可能找錯題 | 原程式只找單一 `body.question` | 遞迴檢索精確子題 ID 與 `my_forecasts` |
| 題庫二元與全格式支援數混淆 | 延用舊欄位名稱 | 分別紀錄 `supported_binary`、`supported_all_formats` |
| 未知複合類型使整份題庫拒絕發布 | 發布器將未知型別視為整批錯誤 | 保留未知型別並標示不支援，不影響其他題 |
| 舊測試預期「未知類型必拒」 | 與保留未知類型的設計衝突 | 增加「未知但不支援可保留、誤標支援必拒」測試 |

## 尚未證實（不得當作成功）

1. **新增數值題已實際通過正式賽提交與回讀**：run 44066723602，題46869、201點CDF（累積分布）、HTTP 201（建立成功）和私人理由回讀均已驗證。**多選、日期、離散三型**仍只完成離線模擬／現有讀題格式驗證，須等真正合格題的完整正式收據。
2. **複合條件題與非標準 Group（群組）子題：** 目前可記錄、支援個別基本型子題的格式／回讀，但不是無條件支援所有複合語意。將失敗標為 `UNSUPPORTED_COMPLEX_TYPE`，不阻擋其餘題。
3. **Work 排程的獨立模型身分收據：** 平台沒有核證字串；依使用者 Work 介面固定 Luna High 及可查的 Sol 子代理執行證據，不因模型口頭自稱而錯誤排除。
4. **官方參賽獲獎資格：** 尚未獨立核實參賽表單／主機器人帳戶，但 API 權杖、讀題及二元正式提交均已成功。

## 下一輪驗收準則

對每一題型分別查核：
A. Work 取得有效題庫 → B. Luna＋Sol 真實研究與分位數／選項機率 → C. 僅加密入隊 → D. Github 真實一次性 POST → E. 官方平台 GET 完整機率向量匹配 → F. 私人理由 POST／GET 確認。

每次 run 以 `FORECAST_AND_PRIVATE_COMMENT_CONFIRMED` 作為正式成功，`NO_ACTION` 表示正常空批；任何 `FORMAT_BLOCKED`、`READBACK_QUESTION_MISMATCH`、`FORECAST_UNCONFIRMED_NEVER_AUTO_RETRY` 必須保留真實錯誤分類、不盲目重送。

參考官方：
- https://www.metaculus.com/api/
- https://github.com/Metaculus/metac-bot-template/blob/main/main_with_no_framework.py
- https://github.com/Metaculus/forecasting-tools/blob/main/forecasting_tools/data_models/numeric_report.py

## 最新真實題庫格式煙霧測試（UTC 10:28）

[Read-only format run 44065034943](https://github.com/Ting-YiLin/metac-bot-template/actions/runs/44065034943) 完成：以現有 MiniBench 開放題的**真實官方上下界和型別**，在記憶體中生成合成分位數作格式檢查（不呼叫提交 API）。當時API回傳3題，其中2題未投；格式檢查 `BinaryQuestion` 1／1 PASS，`NumericQuestion` 1／1 PASS，數值題生成201點CDF；另1題已投故跳過。blocked=0，submitted=0。多選、日期、離散型當時沒有可測真題，不應宣稱它們已通過真實平台端到端測試。


## V2（第二版）最新核定與部署狀態

- 使用者已核准五種題型**按截止時間連續處理當次所有合格題**、不再設每輪2題上限；每題加密入隊並等待對應 GitHub Actions（自動流程）的官方回讀及私人理由收據後，再處理下一題；失敗記錄後繼續下一題。加密機制目前**維持不動**。
- 模型路由改為**盡力完成**：實際 Sol 子代理能完成就用 Sol；失敗／不可建立／超時則主控完成 C 層；缺獨立模型身分核證只記錄 `MODEL_ID_NOT_ATTESTED`（身分未核證），不能因此停止。不得偽造子代理呼叫成功或模型身分。
- 已部署 V2 加密 JSON（資料格式）的 `schema_version=2`，新增 `forecast_author`（最終作者角色）、`subagent_call_status`（子代理呼叫狀態）、`model_attestation`（模型身分核證狀態）；合法回退仍可通過正式提交程式驗證。歷史 V1 信封維持相容。
- 已修改正式提交程式支援同一次 GitHub 工作流程最多24份加密信封，並在同批第二次嘗試相同題號前實施去重；Work 實際流程則按**一題一個提交版本**順序等待收據，沒有整輪總題數限制。
- 使用者已核准修改現有每小時排程提示詞，已更新原「MiniBench Luna／Sol 自動預測」，**沒有新增重複排程**；請以現行 `WORK_LIVE_SCHEDULE_START.md` V2 為唯一正式操作規格。
- 2026-11-17數值題正式證據：[Actions run 44066723602](https://github.com/Ting-YiLin/metac-bot-template/actions/runs/44066723602) 與 [持久收據](https://github.com/Ting-YiLin/metac-bot-template/blob/tingyi001-test-state/state/minibench_live_receipts/run-44066723602.json)，真實預測成功、私人理由成功。
- 尚待：多題連續**真實 Work** 驗收、失敗自動接續真實驗收、排程自主執行證據、三種未提交題型正式回讀。離線測試通過不能充當以上的驗收。

