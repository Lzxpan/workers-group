# Self-improvement policy

Skill Doctor 只接受結構化 `propose`、`simulate`、`apply`、`rollback`，不接受 arbitrary code、shell 或自由格式 patch。所有自動 operation 都需 failing baseline、risk classification、backup、expected SHA-256、isolated validation、完整 tests、獨立 QA `PASS` 與 Boss review。

`learned_skill_rule` 是受限自動學習 operation：它只能在 `SKILL.md` 的 `WG_AUTO_LEARNING_RULES` 標記內追加一條單行規則。這條規則必須源自已驗證的重複失敗或真人修正，且不可以修改權限、模型、sandbox、Hook、script、security、network、刪除、外部帳號／費用、不可逆資料或 model training。符合條件時不等待真人再次確認。

security、sandbox、network、刪除、credentials、外部帳號或費用、不可逆資料、模型訓練、agent 權限與標記區外的核心指揮鏈變更仍是 HIGH risk，停在 `AWAITING_HUMAN_APPROVAL`。

`proposalId` 必須符合 `^[A-Za-z0-9](?:[A-Za-z0-9._-]{0,126}[A-Za-z0-9_-])?$`，且不得使用 Windows reserved device name。`target`、`testEvidence`、`qaEvidence` 及提供時的 Boss evidence 都必須是 Repository 內既存、可讀、regular file；path traversal 與 symlink escape 一律拒絕。

`apply` 不接受 targetless proposal。每一次 apply 都必須帶有符合 operation target class 的 `target`、與檔案內容相符的 `expectedSha256`，以及實際存在且可讀的 test/QA evidence。

LOW risk operation 只能修改固定 target class：

- `update_status_message`：`.codex/hooks.json`
- `retrieval_weights`：`.workers-group/config/retrieval-policy.toml`
- `test_fixture`、`path_fix`：Skill 的 `tests/fixtures/` 或 `tests/scenarios/`
- `diagnostics`：`.workers-group/reports/` 的 JSON、Markdown、text 或 log
- `optional_schema_field`：`.workers-group/schemas/*.schema.json`
- `text_clarification`：非核心的 `hooks-reference.md` 或 `meeting-protocol.md`

`text_clarification` 不得修改 `AGENTS.md`、`SKILL.md`、custom agents、Hooks、任何 scripts 或核心 policy。只有 `learned_skill_rule` 能觸及 `SKILL.md`，而且只能追加到專屬標記區。實際寫入後必須執行 target parse、版本、changelog、Hook prefix 與 Repository Skill validator 等 internal invariants；任一失敗立即 rollback，並保存 rejected fingerprint。

治理 learning 可把已 redacted、已驗證的 failure、真人修正或 QA `PASS` 經驗轉成 Skill Doctor input；完整生命周期見 [learning-and-skill-evolution.md](learning-and-skill-evolution.md)。這不是 model fine-tuning 的授權。Hugging Face model training 不會自動觸發、也不會作為 memory activation、scorecard、meeting decision 或 Skill Doctor proposal 的副作用；任何訓練工作都必須另行取得明確授權，並先定義 dataset、evaluation protocol、cost／hardware decision、token scope 與 Hub persistence plan。

`TRAINING_CANDIDATE` 是本機內部能力缺口 record，不是 external readiness path：它只根據同一能力缺口在最近最多 10 件已驗證任務至少出現 3 次建立，且不含 data、案例、upload、job、Hub 或 credential。只有獨立的 `TRAINING_PROPOSAL` 才能作為 human-only review record，為逐批逐項的人類審查整理候選案例與用途、來源授權、隱私、去識別、license、evaluation、cost、hardware、model license、Hub visibility、rollback；proposal 仍僅供人工決策。training、upload、Hub repository／visibility、credential 使用或任何外部持久化每次都需新的明確 HIGH-risk 人類核准，絕不可由 Skill Doctor `apply`、memory feedback、徽章或 scorecard 自動觸發。
