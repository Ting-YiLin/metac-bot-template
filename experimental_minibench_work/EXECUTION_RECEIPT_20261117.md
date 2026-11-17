# MiniBench 雙模型部署執行收據

日期：2026-11-17（澳洲布里斯本）  
範圍：只讀題庫查詢、真題研究、雙模型 C 判斷與本地 dry-run（模擬不提交）；未提交任何預測。

## 版本與隔離

- 程式庫：`Ting-YiLin/metac-bot-template`
- 分支：`experiment/work-luna-sol-minibench-20261117`
- 執行前分支版本：`9563cfb4d2d09624cd06f048a46f141983f6d17e`
- 固定基準：`f6fbbb0601af8c27caee378a49310d677a77e533`
- 執行前分支與 `main` 的共同祖先等於固定基準；本次變更僅寫入此實驗分支。
- 舊正式工作流程 `.github/workflows/run_live_free.yaml` 未修改，發布 job 仍為 `if: ${{ false }}`。隔離 CI 僅執行單元測試，不讀取憑證、不提交預測。

## S0｜官方題庫與輪次

官方 MiniBench（雙週機器人預測賽）頁確認目前專案 slug（識別碼）為 `minibench`，本輪 2026-11-16 開始、2026-12-04 結束，共60題。官方資料亦說明 MiniBench 題目隨機開放短時段，並非全程都有可預測題。

以公開頁面「New（最新）」排序檢查時，最上方可見題目 ID 46606–46609 顯示尚待揭示／即將揭示或已關閉；沒有在此可見切片中捕捉到一題可核實為「目前開放、尚未由此 bot 預測」的 MiniBench 題。由於 Metaculus API 需要登入憑證，且本次沒有帳戶授權，未能窮舉全部60題，也無法核對 `my_forecasts`（本人預測紀錄）及參賽資格。故本輪正式賽候選狀態為 `NO_ACTION/PARTIAL`，不推論完整題庫沒有開放題。

## 測試題與研究流程

為實際走完研究流程，使用官方 Bot testing area（機器人測試區）開放二元題 43327；它不計分，不能視為本輪 MiniBench 題。

- 題目：Will any of Belgium, France, Italy, Luxembourg, Netherlands, and/or Germany leave the EU before 2027?
- 官方頁狀態：Open（開放）；關閉日 2027-01-01；排定解決日 2027-02-01；公開頁顯示社群預測約1%、624位預測者。
- 結算：六國之一在2027-01-01前依本國憲政要求正式通知歐洲理事會，啟動《歐盟條約》第50條，即判 Yes；歐盟完全解散或改組成不同名稱的歐洲政治經濟聯盟亦判 Yes。毋須等到實際完成退出。
- **A（摘要）**：正式 Article 50 通知才是直接觸發條件；反歐情緒或政黨口號本身不滿足條款。
- **G1（缺口）**：最需要判斷的是六週內是否有成員國政府準備正式通知；最新民調缺荷蘭、比利時、盧森堡，且不能替代政府行動證據。
- **G2（補搜）**：荷蘭眾議院官方紀錄顯示，Stöteler／Wilders要求政府宣布 Nexit（荷蘭退歐）並啟動第50條的動議，僅33票、低於75票門檻，已遭否決；Jetten政府由D66、VVD、CDA組成。Cluster17 2026年1月調查的留歐比例為德79%、法55%、義74%；法國國民聯盟已不主張完整 Frexit（法國退歐），德國AfD文件主張先重談條約、失敗後才公投。
- **B（先驗）**：以公開社群約1%作外部參考錨點，不把它誤稱為獨立歷史基準率。
- **D（反證）**：荷蘭動議證明政治需求存在，是上修訊號；但它未過關且現任執政黨反對。法國、德國的反歐力量也沒有證據顯示會在年底前掌握政府並送出正式通知。低支持率不能排除危機突發，因此保留小幅非零機率。
- **C（最終判斷）**：已建立獨立 `gpt-6.1-sol`、`high`（Sol 6.1 高思考）子代理；其輸出 `p_yes=0.3%`。理由：退出倡議存在，但截至查詢時沒有六國政府即將啟動正式程序的直接證據；荷蘭動議已被否決。主要上修訊號是任何一國內閣正式啟動本國憲政程序並公開設定年底前通知目標。

## E｜格式驗證與不提交測試

1. 執行分支驗證器的11項單元測試：**11/11 通過**。
2. 執行明確標記為 `SYNTHETIC_ONLY_DO_NOT_SUBMIT` 的合成範例：結果 `DRY_RUN_VALID`；`submission_performed=false`。
3. 將題43327真實研究輸出送入同一驗證器：結果 `BLOCKED`，錯誤為 `ROUND_NOT_VERIFIED`、`TOURNAMENT_NOT_VERIFIED`、`ALREADY_FORECASTED_OR_UNKNOWN`、`POST_ID_MISSING`、`INVALID_DEADLINE`；`submission_performed=false`。這是預期安全阻擋：它屬測試區；私人重複預測狀態、API `post_id` 與精確關閉時間不可由本次公開頁面確認。
4. 本次未呼叫任何預測提交／留言 API；沒有平台回讀或真實提交收據。

## 上線驗收表

| 門檻 | 結果 | 裁決 |
|---|---|---|
| 當期 MiniBench 專案與輪次識別 | 官方頁確認 `minibench`、日期及60題 | PASS |
| 當期全部題目／帳戶資格／既有預測狀態 | API需授權；僅完成公開最新切片 | OPEN／PARTIAL |
| 主控模型身份收據 | 沿用本視窗選定模型；介面未回傳可稽核標籤 | OPEN |
| Sol 6.1 High C 階段 | 真實獨立子代理呼叫，取得0.3% | PASS |
| A、G1、G2、B、D、C 研究流程 | 在官方不計分測試區題43327完整執行 | PASS（測試區限定） |
| 二元本地格式驗證器 | 合成範例 PASS；實題因授權／身份資料缺失而 BLOCKED | PASS（阻擋正常） |
| 非二元題型 | 未驗證 | NO-GO |
| 測試區提交與平台回讀 | 未執行 | NOT RUN |
| 正式計分 POST（提交） | 未執行，且本輪未授權 | NO-GO |

**總裁決：NO-GO（不上線正式計分賽）。** 已證明在本工作環境可建立指定 Sol 6.1 High 子代理並完成一題官方測試區的雙模型研究判斷；尚未證明可取得全部當期 MiniBench 候選、確認 bot 帳戶狀態、完成正式輪次真題的端到端驗證或平台回讀。首次正式提交仍需另行核准。

## 官方來源

- MiniBench 輪次頁：<https://www.metaculus.com/tournament/minibench/>
- MiniBench 參與／題目時間與 API 文件：<https://www.metaculus.com/notebooks/38928/docs.adj.news>；<https://www.metaculus.com/api/>
- 測試題 43327：<https://www.metaculus.com/questions/43327/major-state-exits-eu-before-2027/>
- 《歐盟條約》第50條：<https://eur-lex.europa.eu/eli/treaty/teu_2016/2024-09-01>
- 荷蘭眾議院 Nexit 動議與表決：<https://www.tweedekamer.nl/kamerstukken/detail?did=2026D51061&id=2026Z22159>
- Jetten政府組成：<https://www.government.nl/government>
- Cluster17 x Le Grand Continent 歐洲意見調查：<https://cluster17.com/wp-content/uploads/2026/01/Barometre-opinion-publique-europeenne-vague-5-Janvier-2026.pdf>
- AfD 2026年立場報導：<https://www.reuters.com/business/media-telecom/germanys-afd-weighs-shift-anti-eu-roots-strategy-paper-shows-2026-10-05/>
