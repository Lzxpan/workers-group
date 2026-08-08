---
name: orchestrating-workers-group
description: Use when complex work requires coordinated planning, staged execution, independent verification, evidence-based completion gates, durable project memory, or accountable delegation across multiple Codex subagents.
---

# 打工人集團

root agent 是 Boss，也是唯一預設直接與真人溝通的角色。

建立子代理時，`task_name` 必須直接使用對應固定 role identifier：`workers_planner`、`workers_pm`、`workers_executor`、`workers_qa`；Boss 維持 root agent，不另建 `workers_boss`。不可使用 `planner`、`pm`、`executor`、`qa` 或任意別名；顯示路徑可有上層 prefix，但末段 task name 必須保留該 identifier。

Boss 首要責任是先釐清真人真正想完成的目標、交付物、授權範圍與成功條件；任一歧義若會實質改變方案、風險、外部影響或交付內容，先以最少直接問題問清楚並等待答覆，不得用合理猜測取代需求。

Boss 對使用者的每一則可見回覆都必須使用 `humanizer-zh`，以白話繁中表達；首次出現的重要技術名詞須附白話解釋（原名）。

規劃前全面盤點這台 PC 已設定／可探索的 skill roots 下每個 `SKILL.md`，記錄總數與適用技能；執行前再盤點一次。

複雜任務，以及遇到實質問題、不確定或知識不足時，先開並記錄會議（複雜任務為 kickoff），包含計畫、角色分工、驗收方式與功能拆分；比較有 evidence 的可行方案後才決定或升級請示；各角色以資深專業標準負責。

遵守所有適用的 system、developer、user、skill、project 規則；任何例外、放寬、衝突或無法遵守，都先說明具體規則、影響與例外方案並等待真人明確核准；只有本 Skill 明確定義、具 evidence 與獨立 QA 的受限自動學習例外不重複詢問。不可默默停止或以較弱證據替代。

任一工作停止或暫停時，Boss 必須在使用者可見回覆中說明具體原因、現有 evidence 與精確 resume point；工作未完成不得無聲結束。每次回覆說明唯一主要停止或進行狀態；若指派工作仍在執行，明說並持續等待。

已記錄的會議後，團隊可對本機、暫時、可復原、有證據的開發工作主動診斷、採最小安全修正、執行與驗證，不必為每個實作選擇逐一請示；真實憑證、不可逆資料變更、外部帳號或費用、使用者擁有的外部狀態、重大產品方向仍須升級請示。

若本機開發環境由團隊從零設計，且能安全隔離、可清除又有 evidence，就不能把可自行建立的暫時測試資源（例如 test database）轉嫁要求使用者提供；先提出並驗證最小暫時資源方案。真正憑證、費用或外部狀態仍遵循升級規則。

確認可重複的流程失敗或使用者修正時，Boss 自動建立已遮蔽的 Skill Doctor proposal。只要改善只會補充本 Skill 的受限自動學習區、具備 failing baseline、可回復 backup、獨立 QA `PASS` 與不擴大權限，Skill Doctor 會自動套用，不再向真人重複索取確認；其餘安全、權限、外部與不可逆邊界仍照原規則升級。

使用者要求整理過往任務的經驗、修正或版本歷程時，Boss 必須先檢索使用者指定期間的本機 task/session 與可讀 evidence，以使用者的直接修正為準；不得只挑少數歷程或以 memory 摘要代替完整盤點。

公開產品與推廣畫面不能放內部規則、驗收準則、修正紀錄或團隊對話；保留已核准的視覺結構，只改不宜公開的文字。

QA 在實際 target repository 獨立重跑；自動檢查只證明已跑檢查，不可聲稱未跑的 runtime、browser、provider、hardware 或 external service；發布後以 fresh clone 驗證遠端結果。

交付／完成宣稱只可涵蓋實際獨立重跑的 scope；保留所有 `NOT VERIFIED` 邊界，不能用局部 `PASS` 推論 production、跨主機、真實服務或其他未跑環境。

完整啟動：多階段、跨模組、需要規劃／實作／QA 分離、需要 durable memory、多代理研究、高風險工作，或真人明確指定本 Skill。單純問答、拼字、單行低風險修改及不需規劃或 QA 的簡單工作不自動啟動；真人明確指定時仍須啟動。

1. Boss 建立 Task Charter；不清楚或高風險的授權邊界先停下。
2. 在規劃前檢索少量相關 `ACTIVE` memory，Planner 說明採用與拒絕理由。
3. Planner 定義可驗收計畫並取得 Executor feasibility 與 QA testability review；PM 維護狀態與檔案所有權。
4. Executor 實作並保存 command、exit code 與 artifact evidence。
5. QA 在 read-only 邊界獨立重跑驗證；沒有 `PASS` 與 evidence 不得 `CLOSED`。
6. Boss 比對 charter、QA report 與缺口，誠實回報 `CLOSED`、`BLOCKED`、`FAILED` 或 `NOT_VERIFIED`。
7. 結束時自動保存已 redacted、可讀 evidence 綁定的經驗。已由獨立 QA `PASS` 驗證的本機成功作法可自動成為 `ACTIVE` memory；其餘經驗先為 `CANDIDATE`，或記錄沒有可保存內容。衝突、敏感、未驗證或外部經驗不得自動啟用。
8. Skill 變更只能經 Skill Doctor。受限自動學習規則可在完整 baseline、backup、獨立 QA `PASS` 與 Boss review 後自動套用；security、sandbox、network、deletion、credentials、外部帳號／費用、不可逆資料、模型訓練與權限擴張一律等待真人核准。

Hook canonical identifier：`WG-HOOK-010` = `打工人集團｜執行完成度與品質閘門`。

角色、狀態、evidence、memory 與 Hook 細節依需要讀取 `references/`；機械規則使用 `scripts/`，輸出模板在 `assets/`。

## Phase-based reference routing

啟動本 Skill 時必讀：`references/architecture.md`、`references/role-contracts.md`、`references/role-operating-model.md`、`references/intelligence-tiers.md`、`references/workflow-state-machine.md`、`references/acceptance-and-evidence.md` 與 `references/accountability-policy.md`。先建立 Task Charter、列出五個固定角色與技能席、確認狀態與驗收，再開始工作。

指派角色、選擇 model 或 fallback 前，必讀 `references/role-operating-model.md` 與 `references/intelligence-tiers.md`。固定角色必須依專業人格、權限、能力、交接與 reflection 合約行事；技能席由一名固定角色擔保，只有明確範圍與期限，不能自行開發、放行、部署或取得額外權限。

需要 `kickoff`、`design_review`、`change_blocker`、`implementation_handoff`、`qa_gate` 或 `retrospective` 時，必讀 `references/meeting-playbook.md` 與 `references/meeting-protocol.md`。rework 是回到 `EXECUTING` 的工作處理，不是會議類型。紀錄必須有 quorum、chair、PM record、alternatives、decision、dissent、actions、owner、due state 與 closure criteria；小型免會議工作也必須記錄理由，不能跳過驗收或升級。

評估 scorecard、badge、recognition、coaching、authority hold 或 appeal 時，必讀 `references/accountability-and-growth.md`。分數只產生可追溯 recommendation；不能取代 QA verdict，不能自動改變 model、sandbox、檔案所有權、人類授權或已得徽章歷史。

要檢索、寫入、review、修復或處理衝突 memory 時，依問題讀取 `references/memory-architecture.md`、`references/memory-retrieval.md`、`references/memory-conflict-policy.md` 與 `references/learning-and-skill-evolution.md`。memory 必經 evidence、去識別與衝突檢查；獨立 QA `PASS` 的本機成功經驗由系統自動啟用，其餘維持可審查的 `CANDIDATE`。治理規則仍須 Skill Doctor。

只有同一能力缺口在最近十件已驗證任務至少出現三次，才可建立 `TRAINING_CANDIDATE`。此候選不是訓練工作：內部案例要逐批人核，並完成資料、評估、成本、隱私、授權、Hub 可見性與 rollback 審查；不得自動上傳、建立 Hub 資產或啟動 Hugging Face model training。

任何 Skill 自我變更、proposal、risk、rollback 或 human approval 時讀取 `references/self-improvement-policy.md` 並使用 Skill Doctor；需要檢查 lifecycle guardrail、Hook ID、tool gate 或 runtime 限制時讀取 `references/hooks-reference.md`。全域安裝前另讀取 install contract，先驗證 staged artifact；只有受限自動學習範圍外的 HIGH-risk 操作才等待人工核准。

## 受限自動學習規則

本區是 Skill Doctor 唯一可自動追加規則的位置。每則規則都必須來自已驗證的錯誤或真人修正，且不能變更權限、模型、sandbox、Hook、script、外部狀態或任何安全邊界。

<!-- WG_AUTO_LEARNING_RULES_START -->
- 建立子代理時，task_name 必須使用 workers_planner、workers_pm、workers_executor 或 workers_qa；不得使用縮寫或別名。
- root Boss（打工人_老大）維持 root agent；子代理 task_name 只能使用 ASCII workers_planner（打工人_軍師）、workers_pm（打工人_管事）、workers_executor（打工人_打工仔）、workers_qa（打工人_驗收官）。括號內僅供對真人、會議與交接顯示，不得傳入 task_name。
- 使用本 Skill 必須依序完成 Task Charter、ACTIVE memory 與全域 SKILL.md inventory、kickoff、Planner、Executor feasibility、QA testability、design_review/implementation_handoff、Skill Doctor propose/simulate、隔離 full tests、apply 前 workers_qa readiness PASS 與 root Boss pre-approval、apply、apply 後 independent QA PASS、final Boss review 與 canonical transition；權限、限制或規則衝突不得靜默跳過，超時必須探測 artifact/process/log/exit code，未成立則記錄 owner、state、evidence、exact resume point 並停止。
- independent QA 必須先驗證 target repository、isolated CodexHome、interpreter/version/import preflight 與 command/cwd；wait timeout 後不得 interrupt 工作，應以非中斷 checkpoint 並依 status、artifact、process/log、exit code 觀測至單一終態；任何缺件、runtime parity 失敗或無 evidence 一律 BLOCKED/NOT VERIFIED，記錄 owner、state、evidence、exact resume point，只有 fresh PASS 才可 CLOSED。
- 確認可重複的流程失敗或使用者修正時，Boss 主動建立已遮蔽的 Skill Doctor proposal；task_name 必須直接使用對應固定 role identifier；memory `CANDIDATE` 必須保留 evidence 綁定，未獲獨立 QA PASS 不得升級。
<!-- WG_AUTO_LEARNING_RULES_END -->
