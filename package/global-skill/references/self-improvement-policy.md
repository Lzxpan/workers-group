# Self-improvement policy

Skill Doctor 只接受結構化 `propose`、`simulate`、`apply`、`rollback`，不接受 arbitrary code、shell 或自由格式 patch。LOW risk 仍需 failing baseline、risk classification、backup、expected SHA-256、isolated validation、完整 tests、獨立 QA `PASS` 與 Boss review。QA、evidence、security、sandbox、network、刪除、指揮鏈與本政策皆為 HIGH risk，停在 `AWAITING_HUMAN_APPROVAL`。

`proposalId` 必須符合 `^[A-Za-z0-9](?:[A-Za-z0-9._-]{0,126}[A-Za-z0-9_-])?$`，且不得使用 Windows reserved device name。`target`、`testEvidence`、`qaEvidence` 及提供時的 Boss evidence 都必須是 Repository 內既存、可讀、regular file；path traversal 與 symlink escape 一律拒絕。

`apply` 不接受 targetless proposal。每一次 apply 都必須帶有符合 operation target class 的 `target`、與檔案內容相符的 `expectedSha256`，以及實際存在且可讀的 test/QA evidence。

LOW risk operation 只能修改固定 target class：

- `update_status_message`：`.codex/hooks.json`
- `retrieval_weights`：`.workers-group/config/retrieval-policy.toml`
- `test_fixture`、`path_fix`：Skill 的 `tests/fixtures/` 或 `tests/scenarios/`
- `diagnostics`：`.workers-group/reports/` 的 JSON、Markdown、text 或 log
- `optional_schema_field`：`.workers-group/schemas/*.schema.json`
- `text_clarification`：非核心的 `hooks-reference.md` 或 `meeting-protocol.md`

`text_clarification` 不得修改 `AGENTS.md`、`SKILL.md`、custom agents、Hooks、任何 scripts 或核心 policy。實際寫入後必須執行 target parse、版本、changelog、Hook prefix 與 Repository Skill validator 等 internal invariants；任一失敗立即 rollback，並保存 rejected fingerprint。
