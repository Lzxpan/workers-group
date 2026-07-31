# Memory conflict policy

同一 key 的新內容與現有 `ACTIVE` 不一致時，新項目進入 `QUARANTINED`。不得新增 `CONFLICTED`。已被更精確決議取代的項目標示 `SUPERSEDED`；時效性失效標示 `STALE`。衝突未由 Boss 或 QA review 前不得進入 prompt context。
