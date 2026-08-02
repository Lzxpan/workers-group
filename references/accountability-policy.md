# Accountability policy

報告必須區分已驗證事實、假設、推論、未驗證與失敗。Executor 不可為自己的工作簽發 QA verdict；Boss 不能以摘要、時程或聲望取代可讀 evidence 與獨立 QA。

每名固定角色由獨立 reviewer 以 10 個項目各 0 到 10 分評估，總分為 0 到 100。每一分都必須連到可讀 evidence、觀察範圍、限制、反例與 reviewer；缺 evidence 的項目不能給高分。相同人不得評自己的交付、自己的 role performance 或自己的 appeal。

五個共通項目是 `fact_accuracy`、`evidence_completeness`、`scope_discipline`、`handoff_quality`、`early_escalation`。五個角色專屬項目如下：

| Role | 角色專屬項目 |
| --- | --- |
| Boss／老大 | 授權邊界、風險判斷、整合清晰度、真人溝通、品質閘門誠實度 |
| Planner／軍師 | 問題拆解、依賴設計、acceptance 可測性、alternatives 品質、rollback 規劃 |
| PM／管事 | 狀態正確性、所有權完整性、決議可追溯性、blocker 可見性、gate 紀律 |
| Executor／打工仔 | 最小正確實作、工具／測試操作、artifact 可重跑性、failure 診斷、runtime 邊界誠實度 |
| QA／驗收官 | 獨立性、負面驗證、reproduction 品質、verdict 範圍、`NOT VERIFIED` 揭露 |

分數用於可稽核的 recognition、coaching、capability profile 與 appeal；它不是 QA verdict、任務狀態、權限、model、sandbox、檔案所有權或 deployment 的自動控制面。完整 outcome 與複評規則見 [accountability-and-growth.md](accountability-and-growth.md)。
