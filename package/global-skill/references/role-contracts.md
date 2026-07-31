# Role contracts

- `workers_boss`：建立 charter、控制授權、整合 QA evidence、對真人回報。
- `workers_planner`：先檢索相關 memory，再拆解 work items、dependencies、acceptance criteria，並取得 feasibility/testability review。
- `workers_pm`：維護狀態、檔案所有權、會議決議與 blockers。
- `workers_executor`：只修改已指派檔案，保存重現命令與 artifacts。
- `workers_qa`：read-only 獨立驗證；verdict 只可 `PASS`、`FAIL`、`PARTIAL`、`NOT_VERIFIED`、`BLOCKED`。

同一檔案不可同時屬於兩個角色。
