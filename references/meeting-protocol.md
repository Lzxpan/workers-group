# Meeting protocol

只有 [meeting-playbook.md](meeting-playbook.md) 的六個 identifiers 可用作 meeting type：`kickoff`、`design_review`、`change_blocker`、`implementation_handoff`、`qa_gate`、`retrospective`。會議處理跨角色依賴、風險或決策，不能替代 implementation、測試、QA 或真人授權；rework 一律是回到 `EXECUTING` 的工作，不是會議。

會議 record 必須有五角色 quorum 與 PM record，並記錄 attendees、agenda、facts、assumptions、alternatives、decisions、dissent、actions 與 evidence。每次會議提出 2 至 3 個可落實 alternatives；每個 alternative 必含 `description`、`evidence`、`feasibility`、`implementation_impact`、`validation_method`、`risks`、`rollback`、`owner`、`affected_acceptance_criteria`、`affected_memories`、`affected_skill_rules`。不得使用假設不存在的 API 或沒有 evidence 的方案。

每個 action 必含 `description`、`owner`、`due_state`。只要產生 decision，就至少有一個 action；空 action 的 decision 不得視為完成。CLI 使用至少兩個 `--alternative-file PATH` 與 `--action-file PATH` 載入結構化 JSON。會議 closure 只表示 record 完成，絕不表示程式、測試、部署、runtime 或 QA 已完成。
