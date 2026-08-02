# Intelligence tiers

模型選擇要服務角色責任與任務複雜度，不是品質保證。指定模型無法使用、配額／平台限制，或在不降低安全邊界下無法完成必要推理時，才可使用 fallback；不可靜默降級。

| Role | 典型複雜度與專業需求 | Preferred tier | Fallback preconditions | Escalation trigger |
| --- | --- | --- | --- | --- |
| `workers_boss` | 跨角色綜合、授權邊界、風險取捨、最終 evidence gate | `gpt-5.6-sol xhigh` | 原 tier 不可用，且 `gpt-5.6-terra high` 足以維持已定義的 charter 與 evidence gate | fallback 仍無法判定授權、重大風險或 QA 缺口；停止擴權並向真人升級 |
| `workers_planner` | 多階段拆解、依賴分析、可驗收設計、風險推演 | `gpt-5.6-sol xhigh` | 原 tier 不可用，且 `gpt-5.6-terra high` 能以既有 evidence 產出可審查計畫 | acceptance 無法明確、替代方案缺少 evidence，或需改變產品方向 |
| `workers_pm` | 狀態機、檔案所有權、阻塞與決議可追溯性 | `gpt-5.6-sol high` | 原 tier 不可用，且 `gpt-5.6-terra high` 能完整保存狀態與拒絕非法轉換 | 所有權衝突、evidence gate 不完整，或狀態轉換有歧義 |
| `workers_executor` | 精確實作、工具操作、最小修正、可重跑驗證 | `gpt-5.6-terra high` | 原 tier 不可用，且 `gpt-5.6-sol medium` 足以在既有 work item 與檔案所有權內執行 | 修改需越過指派範圍、驗證失敗不明，或需要外部憑證／不可逆動作 |
| `workers_qa` | 對抗性獨立驗證、範圍界定、負面測試與誠實 verdict | `gpt-5.6-sol high` | 原 tier 不可用，且 `gpt-5.6-terra high` 可在 read-only 邊界重跑既定 acceptance commands | 無法獨立重跑、evidence 不可讀，或未驗證範圍可能影響 `PASS` |

Boss、Planner 使用 `gpt-5.6-sol xhigh`；PM、QA 使用 `gpt-5.6-sol high`；Executor 使用 `gpt-5.6-terra high`。Sol/Luna fallback 為 `gpt-5.6-terra high`，Terra fallback 為 `gpt-5.6-sol medium`。Fallback 只記錄在 policy，不放進不支援該欄位的 custom agent TOML。

每次 fallback 必須在 Task Charter、assignment 或可讀 execution record 留下：role、requested tier、selected tier、觸發原因、已知限制、是否影響 acceptance criteria、升級決定與 evidence path。這是能力降級的可稽核記錄，不是對 fallback 結果的背書；仍須依原角色責任完成 evidence 與 `qa_gate`。

## 能力矩陣與技能席

模型 tier 是工具選擇，能力門檻則是角色可承接範圍的 evidence 要求。下表的「能力證明」由近 10 個已驗證任務的 capability profile 支持，不用自我評價、單次成功或模型名稱取代；不足時縮小 scope、加入受擔保的技能席，或升級給 Boss。

| 固定角色 | 核心能力 | 承接較高風險／複雜度前的能力證明 | 可使用的技能席輸出 |
| --- | --- | --- | --- |
| Boss／老大 | 授權判斷、跨角色綜合、風險與 evidence gate | 近 10 件中能清楚處理 scope、未驗證邊界與 QA 缺口，且沒有以完成話術掩蓋 blocker | 風險、法規、產品或領域 alternatives；Boss 保留決定權 |
| Planner／軍師 | 問題拆解、依賴、可測 acceptance 與 rollback | 近 10 件中 plan 的 work item、owner、驗證可被 Executor／QA 接受並實際重跑 | 領域設計、演算法或架構建議；Planner 轉成可驗收計畫 |
| PM／管事 | 狀態、所有權、決議、阻塞與時間序 | 近 10 件中無未處理所有權衝突或非法 gate 推進 | 流程分析與風險清單；PM 維護唯一狀態帳本 |
| Executor／打工仔 | 最小實作、工具鏈、可重跑 evidence 與 rollback | 近 10 件中命令、artifact、失敗與 runtime 邊界可由 QA 重現 | 專門技術調查或實作 alternatives；Executor 才能修改 owned files |
| QA／驗收官 | 對抗驗證、負面路徑、provenance 與 honest verdict | 近 10 件中 verdict 範圍與獨立重跑 record 一致，未把 compile 當 runtime 證明 | 測試設計或領域檢核清單；QA 保留 read-only verdict |

技能席永遠是受 sponsor 約束的暫時顧問。它的推薦不改變 preferred tier、fallback 記錄、固定角色的 evidence 義務或任何 human authorization。
