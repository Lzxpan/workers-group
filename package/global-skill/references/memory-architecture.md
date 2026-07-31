# Memory architecture

SQLite 是 operational store；JSONL 是可讀 export。寫入先經 `memory_guard.py`，新項目一律 `CANDIDATE`。轉為 `ACTIVE` 不能只依賴 caller 提供的 actor label；必須提交結構化 reviewer artifact，將 `memory_id`、Boss/QA reviewer、`APPROVED` 或相容的 QA `PASS` verdict 與 memory evidence 精確綁定。Memory evidence、review artifact evidence 及 CLI 提供的 artifact file 都必須是 Repository 內既存、可讀的 regular file；audit log 保存 artifact path 與 SHA-256。資料表、FTS5、transaction、WAL、busy timeout、integrity check 與 backup 的實作位於 memory scripts。

Working Memory 位於 `.workers-group/state/`，不視為永久知識。SQLite durable memory 的 `memoryType` 只接受 `EPISODIC`、`SEMANTIC`、`PROCEDURAL`、`DECISION`、`FAILURE`、`PREFERENCE`、`SKILL_EVOLUTION`；舊資料 migration 預設為 `SEMANTIC`。`PREFERENCE` 僅能保存使用者明確表達且與 Repository 工作直接相關的偏好，不得擴大推論個人資料。

JSONL export 保存 memories 的完整 provenance、timestamps、counters、expiry、sensitivity 與 activation，並另外保存 relations、retrieval ledger、audit log 及 schema migration records。`memory_repair.py repair` 對 corrupt DB 一律先備份；明確指定且通過 integrity/security validation 的 SQLite backup 優先。沒有合法 backup 時才在隔離暫存 DB 以受 guard 的 export 做 transaction import，通過 `integrity_check` 後才原子替換；任一 validation/import/integrity 失敗都保留原 DB，不以空白 DB 靜默取代。
