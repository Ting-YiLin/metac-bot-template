# BTF-3 A/C 雲端爬蟲接力入口（已隔離於實驗分支）

- 程式庫：https://github.com/Ting-YiLin/metac-bot-template
- 實驗分支：btf3-llm-crawler-bridge-v1-20261103
- 爬蟲：web_research_stack/src/crawler.py
- 免費搜尋：web_research_stack/src/search_backends.py
- 歷史快照：web_research_stack/src/wayback.py
- 接力執行器：web_research_stack/src/llm_ac_bridge.py
- 自動工作流程：.github/workflows/btf3_llm_ac_bridge.yaml

這個接力器只讓 A、C 組呼叫免費搜尋或歷史爬取；並不呼叫任何 LLM，也不會提交競賽預測。
每一輪分成兩次指令：

1. 模型先根據題目自行產生最多2個查詢，透過 GitHub 連線於指定分支建立一個新檔案：
   bridge_requests/A/Q001_R1_SEARCH_001.json
   只需新建檔案，推送動作會觸發 Actions。A、C 必須用不同的 A/C 目錄。
   內容例：
   {"arm":"A","task":"search","case_id":"Q001","round":1,
    "question":"<從工作包逐字抄題目>","t0_utc":"<從工作包逐字抄T0>",
    "queries":["<模型提出的查詢一>","<模型提出的查詢二>"]}

2. 打開 GitHub Actions 中最新的 BTF3 LLM A-C Free Crawler Bridge，
   確認成功，下載 btf3-llm-bridge-<執行編號> 成果，讀取
   BRIDGE_RESULT.json 裡的真實 DDGS 搜尋結果。
   模型只可從實際返回的候選 URL 選最多2條，再建立不同的新檔：
   bridge_requests/A/Q001_R1_FETCH_001.json
   內容例：
   {"arm":"A","task":"fetch","case_id":"Q001","round":1,
    "question":"<同原題>","t0_utc":"<同T0>",
    "urls":["<真實搜尋結果內選出的URL>"],
    "search_candidate_urls":["<本次搜尋結果全部候選URL，最多16條>"]}
   C組上述JSON須另加 "rules_sha256":"<先凍結的64字元SHA-256>"。

3. Actions 再執行嚴格 T0 前 Wayback 查找、robots.txt 遵從、
   安全爬取與原件/全文 SHA-256 驗證；相同方式下載成果，
   閱讀 BRIDGE_RESULT.json 及 crawl/text 下實際正文，判斷缺口。
   不能把未驗證、搜尋摘要、T0後內容當合格歷史證據。

4. 維護實驗工作包內的 results/events.jsonl，逐題記錄每個真實請求
   和 GitHub run id、URL、來源、文字片段與模型用量；
   每題最多3輪，每輪最多2查詢＋2抓取。**雲端接力每次無狀態，
   整體輪次/額度必須由實驗視窗及主控交接紀錄共同核對**。

權限/限制：
- 新視窗須實際具有 GitHub 連線的檔案新增、工作紀錄讀取、
  成果下載權限；連上 GitHub 本身不代表自動能執行。
- 若雲端任務失敗，先回報該執行的實際日誌與阻塞原因，不得
  改用付費工具、偽造結果、將當前網頁冒充截止前。
- 使用不同檔名，不得覆蓋舊請求，亦不得修改主分支或預測機器人。
- 本輪是 RETROSPECTIVE_DIAGNOSTIC_ONLY（回溯診斷），
  活動搜尋可能含事後發現偏差，不是歷史盲測。
- B組不得使用本接力器或自動爬蟲；只准其原生瀏覽模式。

GitHub 實作示範以連接器新增檔案；若沒有 GitHub 連接器，
可以透過 GitHub 網站在指定分支手動新增檔案，或回報 BLOCKED。
