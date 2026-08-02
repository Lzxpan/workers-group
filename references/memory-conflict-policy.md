# Memory conflict policy

同一 key 的新內容與現有 `ACTIVE` 不一致時，新項目進入 `QUARANTINED`。不得新增 `CONFLICTED`。已被更精確決議取代的項目標示 `SUPERSEDED`；時效性失效標示 `STALE`。衝突未由 Boss 或 QA review 前不得進入 prompt context。

反例、來源撤回、expiry 或新 evidence 觸發的「撤回」是治理處置，不是新增 database status：PM 記錄撤回原因與 evidence，相關角色評估 scope，Boss 或合格 QA reviewer 依現有 `QUARANTINED`、`SUPERSEDED`、`STALE` 與 audit policy 作出可追溯處理。已撤回／隔離內容不得進入 prompt context，也不得因舊的 positive scorecard、badge 或 retrieval counter 恢復使用。
