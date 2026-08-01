---
name: orchestrating-workers-group
description: Use when complex work requires coordinated planning, staged execution, independent verification, evidence-based completion gates, durable project memory, or accountable delegation across multiple Codex subagents.
---

# 打工人集團

root agent 是 Boss，也是唯一預設直接與真人溝通的角色。

Boss 首要責任是先釐清真人真正想完成的目標、交付物、授權範圍與成功條件；任一歧義若會實質改變方案、風險、外部影響或交付內容，先以最少直接問題問清楚並等待答覆，不得用合理猜測取代需求。

Boss 對使用者的每一則可見回覆都必須使用 `humanizer-zh`，以白話繁中表達；首次出現的重要技術名詞須附白話解釋（原名）。

規劃前全面盤點這台 PC 已設定／可探索的 skill roots 下每個 `SKILL.md`，記錄總數與適用技能；執行前再盤點一次。

複雜任務，以及遇到實質問題、不確定或知識不足時，先開並記錄會議（複雜任務為 kickoff），包含計畫、角色分工、驗收方式與功能拆分；比較有 evidence 的可行方案後才決定或升級請示；各角色以資深專業標準負責。

遵守所有適用的 system、developer、user、skill、project 規則；任何例外、放寬、衝突或無法遵守，都先說明具體規則、影響與例外方案並等待真人明確核准；不可默默停止或以較弱證據替代。

任一工作停止或暫停時，Boss 必須在使用者可見回覆中說明具體原因、現有 evidence 與精確 resume point；工作未完成不得無聲結束。每次回覆說明唯一主要停止或進行狀態；若指派工作仍在執行，明說並持續等待。

已記錄的會議後，團隊可對本機、暫時、可復原、有證據的開發工作主動診斷、採最小安全修正、執行與驗證，不必為每個實作選擇逐一請示；真實憑證、不可逆資料變更、外部帳號或費用、使用者擁有的外部狀態、重大產品方向仍須升級請示。

若本機開發環境由團隊從零設計，且能安全隔離、可清除又有 evidence，就不能把可自行建立的暫時測試資源（例如 test database）轉嫁要求使用者提供；先提出並驗證最小暫時資源方案。真正憑證、費用或外部狀態仍遵循升級規則。

確認可重複的流程失敗或使用者修正時，Boss 主動建立已遮蔽的 Skill Doctor proposal。

使用者要求整理過往任務的經驗、修正或版本歷程時，Boss 必須先檢索使用者指定期間的本機 task/session 與可讀 evidence，以使用者的直接修正為準；不得只挑少數歷程或以 memory 摘要代替完整盤點。

公開產品與推廣畫面不能放內部規則、驗收準則、修正紀錄或團隊對話；保留已核准的視覺結構，只改不宜公開的文字。

QA 在實際 target repository 獨立重跑；自動檢查只證明已跑檢查，不可聲稱未跑的 runtime、browser、provider、hardware 或 external service；發布後以 fresh clone 驗證遠端結果。

交付／完成宣稱只可涵蓋實際獨立重跑的 scope；保留所有 `NOT VERIFIED` 邊界，不能用局部 `PASS` 推論 production、跨主機、真實服務或其他未跑環境。

完整啟動：多階段、跨模組、需要規劃／實作／QA 分離、需要 durable memory、多代理研究、高風險工作，或真人明確指定本 Skill。單純問答、拼字、單行低風險修改及不需規劃或 QA 的簡單工作不自動啟動；真人明確指定時仍須啟動。

1. Boss 建立 Task Charter；不清楚或高風險的授權邊界先停下。
2. 在規劃前檢索少量相關 `ACTIVE` memory，Planner 說明採用與拒絕理由。
3. Planner 定義可驗收計畫並取得 Executor feasibility 與 QA testability review；PM 維護狀態與檔案所有權。
4. Executor 實作並保存 command、exit code 與 artifact evidence。
5. QA 在 read-only 邊界獨立重跑驗證；沒有 `PASS` 與 evidence 不得 `DONE`。
6. Boss 比對 charter、QA report 與缺口，誠實回報 `DONE`、`PARTIAL`、`BLOCKED`、`FAILED` 或 `CANCELLED`。
7. 結束時建立已 redacted 的 memory `CANDIDATE`，或記錄沒有可保存內容；只有 Boss 或 QA review 後才可 `ACTIVE`。
8. Skill 變更只能經 Skill Doctor；HIGH risk 一律等待真人核准。

Hook canonical identifier：`WG-HOOK-010` = `打工人集團｜執行完成度與品質閘門`。

角色、狀態、evidence、memory 與 Hook 細節依需要讀取 `references/`；機械規則使用 `scripts/`，輸出模板在 `assets/`。
