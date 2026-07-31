# Workflow state machine

主路徑：`INTAKE → CHARTERED → PLANNING → FEASIBILITY_REVIEW → READY → EXECUTING → READY_FOR_QA → QA_REVIEW → READY_FOR_BOSS_REVIEW → DONE`。

例外狀態是 `BLOCKED`、`NEEDS_REWORK`、`QA_FAILED`、`PARTIAL`、`FAILED`、`CANCELLED`。`READY_FOR_QA` 需要完整 Executor evidence；`READY_FOR_BOSS_REVIEW` 需要 QA `PASS` 或真人 waiver；`DONE` 需要 Boss review、全數 criteria 通過、可讀 evidence、失敗揭露、memory candidate decision，以及 Skill 版本／rollback 紀錄。不合法轉換由 `validate_transition.py` 拒絕。

CLI 可用 `--actor ROLE --reason TEXT --audit-path PATH` 將成功或拒絕的驗證結果 append 至 JSONL audit。每筆事件包含 `timestamp`、`actor`、`previous_status`、`new_status`、`reason`、`evidence`、`related_acceptance_criteria`、`task_id`、`accepted` 與拒絕原因；拒絕事件不會被當成成功轉換。
