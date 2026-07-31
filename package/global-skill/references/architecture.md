# Architecture

`AGENTS.md` 與 version-controlled policy 是治理權威；Skill 負責流程，scripts 負責機械判斷。`.codex/agents/` 定義角色，`.codex/hooks.json` 提供 lifecycle guardrails，`.workers-group/` 保存 schema、reports、curated memory 與可回復變更。Hooks 不連網，也不保存 raw transcript。
