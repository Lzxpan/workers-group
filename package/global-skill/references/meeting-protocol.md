# Meeting protocol

只在角色間有實質依賴、風險或決策時開會。記錄 attendees、agenda、facts、assumptions、alternatives、decisions、actions 與 evidence。會議不能替代測試。

每次會議必須提出 2 到 3 個可落實 alternatives。每個 alternative 必須包含 `description`、`evidence`、`feasibility`、`implementation_impact`、`validation_method`、`risks`、`rollback`、`owner`、`affected_acceptance_criteria`、`affected_memories` 與 `affected_skill_rules`。不得使用假設不存在的 API 或沒有 evidence 的幻想方案。

每個 action 必須包含 `description`、`owner` 與 `due_state`。只要產生 decision，就至少要有一個 action；空 action 的 decision 不得視為完成。CLI 使用至少兩個 `--alternative-file PATH`，並用 `--action-file PATH` 載入結構化 JSON。
