# Architecture

`AGENTS.md` 與 version-controlled policy 是治理權威；Skill 負責流程，scripts 負責機械判斷。`.codex/agents/` 定義五個固定角色（Boss／老大、Planner／軍師、PM／管事、Executor／打工仔、QA／驗收官），`.codex/hooks.json` 提供 lifecycle guardrails，`.workers-group/` 保存 schema、reports、curated memory 與可回復變更。Hooks 不連網，也不保存 raw transcript。

技能席是由固定角色擔保的暫時顧問輸入，不是 `.codex/agents/` 的第六個 authority plane。治理文字、scorecard、memory candidate、內部 `TRAINING_CANDIDATE` 或 human-only `TRAINING_PROPOSAL` 不能自行變更 scripts、schema、agent model、sandbox、權限或 Hook runtime；這些變更仍需各自的版本控制與授權流程。
