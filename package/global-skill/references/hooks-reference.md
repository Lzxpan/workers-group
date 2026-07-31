# Hooks reference

| ID | Event | Display |
|---|---|---|
| WG-HOOK-001 | SessionStart | 打工人集團｜載入任務與長期記憶 |
| WG-HOOK-002 | UserPromptSubmit | 打工人集團｜分析需求與啟動團隊 |
| WG-HOOK-003 | SubagentStart | 打工人集團｜注入子代理角色規範 |
| WG-HOOK-004 | SubagentStop | 打工人集團｜驗證子代理工作報告 |
| WG-HOOK-005 | PreToolUse | 打工人集團｜工具安全與範圍檢查 |
| WG-HOOK-006 | PermissionRequest | 打工人集團｜審查高風險操作 |
| WG-HOOK-007 | PostToolUse | 打工人集團｜收集測試與建置證據 |
| WG-HOOK-008 | PreCompact | 打工人集團｜保存壓縮前任務狀態 |
| WG-HOOK-009 | PostCompact | 打工人集團｜恢復壓縮後任務狀態 |
| WG-HOOK-010 | Stop | 打工人集團｜執行完成度與品質閘門 |
| WG-HOOK-011 | SessionEnd | 打工人集團｜封存工作經驗與記憶 |

Tool matcher 使用 Codex canonical names：`Bash|apply_patch|Edit|Write|Agent`。`PreToolUse` 高風險拒絕使用 nested `hookSpecificOutput.permissionDecision: deny`；`PermissionRequest` 使用 nested `hookSpecificOutput.decision.behavior: deny`，不自動批准。Top-level `decision: block` 只用於 `Stop`／`SubagentStop` continuation。

`SubagentStop` 與 `Stop` 會同時檢查 payload 與 `.workers-group/runtime/active-task.json`。有缺口且低於上限時輸出 `decision: block`；最多 continuation 2 次，達上限後要求 Boss 回報 `PARTIAL`、`BLOCKED` 或 `FAILED`。

`SubagentStart` 注入精簡 role/task contract；`PostToolUse` 只保存有證據價值且已 redacted 的摘要；`PreCompact`／`PostCompact` 保存與恢復白名單狀態；`SessionEnd` 只寫 session metadata 與 pending memory candidate，不保存 raw transcript。

Repository Hooks 仍須在新 Codex session 由真人使用 `/hooks` review/trust；direct invocation 不能替代 UI runtime 驗證。
