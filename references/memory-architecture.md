# Memory architecture

SQLite 是 operational store；JSONL 是可讀 export。寫入先經 `memory_guard.py`，新項目一律 `CANDIDATE`。轉為 `ACTIVE` 不能只依賴 caller 提供的 actor label；必須提交結構化 reviewer artifact，將 `memory_id`、Boss/QA reviewer、`APPROVED` 或相容的 QA `PASS` verdict 與 memory evidence 精確綁定。Memory evidence、review artifact evidence 及 CLI 提供的 artifact file 都必須是 Repository 內既存、可讀的 regular file；audit log 保存 artifact path 與 SHA-256。資料表、FTS5、transaction、WAL、busy timeout、integrity check 與 backup 的實作位於 memory scripts。

Working Memory 位於 `.workers-group/state/`，不視為永久知識。SQLite durable memory 的 `memoryType` 只接受 `EPISODIC`、`SEMANTIC`、`PROCEDURAL`、`DECISION`、`FAILURE`、`PREFERENCE`、`SKILL_EVOLUTION`；舊資料 migration 預設為 `SEMANTIC`。`PREFERENCE` 僅能保存使用者明確表達且與 Repository 工作直接相關的偏好，不得擴大推論個人資料。

JSONL export 保存 memories 的完整 provenance、timestamps、counters、expiry、sensitivity 與 activation，並另外保存 relations、retrieval ledger、audit log 及 schema migration records。`memory_repair.py repair` 對 corrupt DB 一律先備份；明確指定且通過 integrity/security validation 的 SQLite backup 優先。沒有合法 backup 時才在隔離暫存 DB 以受 guard 的 export 做 transaction import，通過 `integrity_check` 後才原子替換；任一 validation/import/integrity 失敗都保留原 DB，不以空白 DB 靜默取代。

治理學習的操作順序是 evidence → redaction → `CANDIDATE` → authorized review → `ACTIVE` → retrieval／feedback → Skill Doctor proposal → HIGH risk human approval。完整的角色分工與停止點見 [learning-and-skill-evolution.md](learning-and-skill-evolution.md)。一段工作經驗不可因為有用、分數高或提案存在而直接提升為 `ACTIVE`；仍須遵循本文件定義的 reviewer artifact、evidence binding 與 audit log。

## v2 記憶閉環與分類

v2 的操作閉環是 evidence → 去識別／sensitivity 分級 → `CANDIDATE` → 相關固定角色審查 → Boss／老大授權 review → retrieval feedback → retro → Skill Doctor。QA／驗收官可驗證 evidence 或擔任合格 reviewer，但任何角色、retro、rubric 或徽章都不能跳過 structured reviewer artifact 直接把 candidate 變成 `ACTIVE`。

每項 candidate 必須可追溯地記錄來源、scope、期限／expiry、sensitivity、支持 evidence、反例／限制與撤回條件。內容分類為「任務事實」、「可泛化方法」或「治理規則」；這些是治理分類標籤，不新增 SQLite `memoryType` enum。寫入時仍使用既有允許的 `memoryType`：例如任務事實依內容用 `EPISODIC`／`SEMANTIC`，可泛化方法用 `PROCEDURAL`，治理規則用 `DECISION` 或 `SKILL_EVOLUTION`。若未來要新增 enum、欄位或 migration，必須另走已核准的 schema／Skill Doctor 流程。

撤回不是刪除歷史：當來源被否定、期限到期、反例推翻結論、隱私風險上升或真人要求撤回時，保留 audit provenance，停止檢索，並依現有 `QUARANTINED`、`SUPERSEDED`、`STALE` 等合法狀態與 conflict policy 處理。不得虛構新的儲存狀態或以空白資料庫覆蓋原資料。
