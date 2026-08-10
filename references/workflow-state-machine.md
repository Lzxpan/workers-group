# Workflow state machine

本文件的 v2 lifecycle 只有下列 12 個 canonical states；任何 report、meeting、handoff 與 governance record 都使用這些名稱：

1. `INTAKE`：接收需求，尚未形成治理工作。
2. `KICKOFF`：依 `verification_mode` 由四個 basic 角色，或加上 strict-only QA，確認任務、範圍、分工、驗收與已知限制。
3. `PLANNING`：建立可驗證的 work items、所有權、alternatives、evidence 與 rollback。
4. `AWAITING_HUMAN_APPROVAL`：需要新的真人決策或授權，相關動作停止。
5. `EXECUTING`：在明確 owned files 與授權內實作或執行工作。
6. `EVIDENCE_REVIEW`：檢查 execution evidence 的可讀性、provenance 與 handoff 完整性；不是 QA `PASS`。
7. `QA`：只有 `strict` path 使用；QA 在 read-only 邊界獨立重跑並給出實際範圍的 verdict。
8. `BOSS_REVIEW`：basic 由 Boss 比對 charter、`boss_verification`、授權與未驗證邊界；strict 另比對 QA evidence。
9. `CLOSED`：已依可讀 evidence 結案，並保留 learning decision 與未驗證邊界。
10. `BLOCKED`：缺少依賴、evidence、所有權或必要決策；record 必須有 owner、原因與 resume target。
11. `FAILED`：已驗證無法滿足工作目標或安全界線；record 必須有 failure evidence 與後續選項。
12. `NOT_VERIFIED`：所需環境、服務、hardware、browser、provider 或行為尚未實際執行；record 必須說明未驗證原因與 resume target，不能用 compile success 補足。

basic 標準前進路徑為 `INTAKE → KICKOFF → PLANNING → EXECUTING → EVIDENCE_REVIEW → BOSS_REVIEW → CLOSED`；strict 標準前進路徑才經過 `QA`。需要真人決策時進入 `AWAITING_HUMAN_APPROVAL`，取得明確決策後回到 `PLANNING` 或 `EXECUTING`。任一非結案工作若遇缺口可進入 `BLOCKED`；解除後回到 record 指定的 resume target。任一需要實際觀察但尚未執行的範圍可進入 `NOT_VERIFIED`；完成該觀察後回到對應的 `EXECUTING`、`EVIDENCE_REVIEW` 或 strict `QA`。`FAILED` 是失敗結案，`CLOSED` 只用於 evidence 支持的結案。

rework 不是 state 或 meeting type。當 basic `boss_verification`、strict QA verdict、evidence 或 Boss review 要求修正時，PM 建立新的 owned work item，將工作返回 `EXECUTING`，並保留原有 failure／verdict evidence。strict path 不得在尚未重跑 QA 前回到 `BOSS_REVIEW`。

每次狀態轉換都要留下 task ID、前後 state、actor、reason、相關 acceptance criteria、evidence paths、時間與拒絕／限制資訊。狀態名稱本身不證明 runtime、deployment、外部服務或跨主機行為；只有實際 evidence 支持的 scope 可以在 `CLOSED` 對外宣稱。
