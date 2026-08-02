# Meeting playbook

meeting type identifiers 只有 `kickoff`、`design_review`、`change_blocker`、`implementation_handoff`、`qa_gate`、`retrospective`。除獨立、低風險、已有明確 owner 與 acceptance、沒有共用決策的微小工作外，治理會議的 quorum 是五個固定角色；PM／管事必須保存 record。技能席只能由 sponsor 帶入 evidence，不計入 quorum、不可投票、不可放行。

每次會議都要記錄 attendees、agenda、verified facts、assumptions、2 至 3 個 evidence-backed alternatives、decision、dissent、actions、owner、`due_state`、artifact path、影響的 acceptance criteria、下一個 canonical state，以及是否需要真人決策。quorum 不足時，PM 記錄 `BLOCKED` 與 resume condition；不得以沉默視為同意。需要新真人決策時只形成清楚問題、alternatives 與安全暫停點，狀態為 `AWAITING_HUMAN_APPROVAL`。

## kickoff

**Trigger:** 進入治理工作。**Input:** 目標、授權、限制、已知 evidence、技能席需求與 `NOT VERIFIED`。**Output:** Task Charter、五角色 ownership、acceptance、初始風險與 state `KICKOFF`。**Closure:** Planner 可開始 `PLANNING`，或明確等待真人授權。

## design_review

**Trigger:** 建立或改動 plan、architecture、依賴、acceptance 或 rollback。**Input:** alternatives、current evidence、Planner draft、Executor feasibility、QA testability。**Output:** 可驗證 plan、dissent、work items 與 owners。**Closure:** 進入或維持 `PLANNING`；未解決的安全／授權問題進入 `AWAITING_HUMAN_APPROVAL`。

## change_blocker

**Trigger:** scope、風險、外部影響、fallback、所有權衝突或失敗需要決定。**Input:** blocker evidence、可逆 alternatives、受影響 scope、rollback。**Output:** 選定安全路徑或真人問題、owner 與 resume condition。**Closure:** 解除時回到指定 state；未解除時為 `BLOCKED` 或 `AWAITING_HUMAN_APPROVAL`。

## implementation_handoff

**Trigger:** Planner → Executor、Executor → QA 或修正後重新交付。**Input:** owned files、exact command、cwd、exit code、passed、failed、skipped、artifact、rollback 與 `NOT VERIFIED`。**Output:** 接收／拒收 record、下一 owner 與 state。**Closure:** 接收者能獨立定位 evidence；否則 PM 記錄 `BLOCKED`。

## qa_gate

**Trigger:** `EVIDENCE_REVIEW` 後進入 QA，或修正後需重新驗證。**Input:** frozen acceptance、read-only commands、preconditions、artifacts、failure history。**Output:** QA verdict、evidence、reproduction、受影響 scope 與未驗證邊界。**Closure:** 可讀 QA `PASS` 才能到 `BOSS_REVIEW`；其他結果回到 `EXECUTING`、`BLOCKED`、`FAILED` 或 `NOT VERIFIED`。

## retrospective

**Trigger:** `CLOSED`、`FAILED` 或同類問題重複。**Input:** verified results、失敗、rubric／capability profile、memory feedback 與未驗證邊界。**Output:** redacted memory candidate、Skill Doctor proposal 或「沒有可保存內容」。**Closure:** 不會直接激活 memory、改權限、提交 training 或改變 QA verdict。

rework 不是 state 或 meeting type。它表示 QA、evidence 或 Boss review 要求新的修正工作；PM 建立 owned work item，保留原 evidence，並使工作返回 `EXECUTING`。需要計畫調整時使用 `design_review`，需要風險決策時使用 `change_blocker`，需要重新交付或驗證時使用 `implementation_handoff` 或 `qa_gate`。
