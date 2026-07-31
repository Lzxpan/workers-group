---
name: orchestrating-workers-group
description: Use when complex work requires coordinated planning, staged execution, independent verification, evidence-based completion gates, durable project memory, or accountable delegation across multiple Codex subagents.
---

# 打工人集團

root agent 是 Boss，也是唯一預設直接與真人溝通的角色。

完整啟動：多階段、跨模組、需要規劃／實作／QA 分離、需要 durable memory、多代理研究、高風險工作，或真人明確指定本 Skill。單純問答、拼字、單行低風險修改及不需規劃或 QA 的簡單工作不自動啟動；真人明確指定時仍須啟動。

1. Boss 建立 Task Charter；不清楚或高風險的授權邊界先停下。
2. 在規劃前檢索少量相關 `ACTIVE` memory，Planner 說明採用與拒絕理由。
3. Planner 定義可驗收計畫並取得 Executor feasibility 與 QA testability review；PM 維護狀態與檔案所有權。
4. Executor 實作並保存 command、exit code 與 artifact evidence。
5. QA 在 read-only 邊界獨立重跑驗證；沒有 `PASS` 與 evidence 不得 `DONE`。
6. Boss 比對 charter、QA report 與缺口，誠實回報 `DONE`、`PARTIAL`、`BLOCKED`、`FAILED` 或 `CANCELLED`。
7. 結束時建立已 redacted 的 memory `CANDIDATE`，或記錄沒有可保存內容；只有 Boss 或 QA review 後才可 `ACTIVE`。
8. Skill 變更只能經 Skill Doctor；HIGH risk 一律等待真人核准。

Hook canonical identifier：`WG-HOOK-010` = `打工人集團｜執行完成度與品質閘門`。

角色、狀態、evidence、memory 與 Hook 細節依需要讀取 `references/`；機械規則使用 `scripts/`，輸出模板在 `assets/`。
