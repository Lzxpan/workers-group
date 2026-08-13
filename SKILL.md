---
name: orchestrating-workers-group
description: Use when complex, multi-step, or explicitly requested work needs Boss, Planner, PM, and Executor coordination with required Skill compliance and completion checks.
---

# 打工人集團

使用四個固定角色，把複雜工作拆成可交付成果，並確實遵守每個 work item 指定的 Skills。

## 固定角色

- `/root` 是唯一 Boss：確認目標、選擇 Skills、分派工作、處理規則衝突，並直接向真人回覆。
- `workers_planner`：定義會產出使用者要求交付物的 work items、ownership、完成條件與 `required_skills`。
- `workers_pm`：檢查工作完成度與本 Skill 流程是否被遵守。
- `workers_executor`：只完成已分配檔案，並為自己的 work item 做最低限度自檢。

不得建立上述以外的角色。

## 執行流程

1. Boss 在規劃前盤點本機 Skills，判斷本任務是否需要本 Skill，並在對真人的繁體中文回覆使用 `humanizer-zh`。
2. Boss 先提供 candidate Skills 的名稱與精確 `SKILL.md` 路徑。Planner 規劃前讀取本 Skill，且只完整讀取明確分配給 Planner 本人的 Skill；它以 candidate 清單選取並列出 `required_skills`，不因候選或分配給 Executor 的 Skill 完整讀取而延後 work item。這不是略過 Skill：Boss 分配 work item 後，由負責角色完整讀取自己獲配的 Skills 與明確要求的 references。若存在 Git root，Planner 只以已知任務關鍵字對 `<repo>/.workers-group/lessons.md` 做一次有界 `rg -n -i -C 3` 搜尋；檔案不存在或沒有相符 lessons 時，記錄「沒有相符 lessons」後直接規劃，不擴大關鍵字、不讀完整 lessons、也不掃描更大範圍。在 work item 中列出沿用的有效做法與避免錯誤。接著為每個 work item 寫出：目標、owned files、交付物、完成條件、`required_skills`。每個 required Skill 都列出名稱與精確 `SKILL.md` 路徑。每個 work item 都必須產出使用者要求的交付物；不得新增確認型、檢查型或報告型 work item。若已知資訊仍缺少必要授權或重大決策，Planner 只回覆 Boss 一項具體缺口與證據，不持續探索或等候。
3. PM 先檢查 Planner 的 work items 是否完整，特別確認 `required_skills`、ownership 與完成條件。缺件時交回 Boss 補正後才開始實作。
4. Boss 在執行前再次盤點本機 Skills，將 work item 和 required Skill 路徑交給負責角色。
5. Boss 分配 work item 後，每個負責角色先完整讀取自己獲配的 `SKILL.md` 及其明確要求的 references，再開始工作；Planner 的 candidate 選取不取代這項完整讀取。
6. Executor 只修改 owned files，完成後為自己的 work item 執行最貼近修改內容的一項現有測試、build 或 parser check；沒有可執行檢查時，直接記錄原因。對同一直接交付 work item，只有具備 Git root 與 lessons ownership 時，才更新 `<repo>/.workers-group/lessons.md`；沒有可重用教訓時不建檔也不修改，無 Git root 或 ownership 時在回報標示未持久化。不得新增檢查型 work item、第二位確認者或額外報告鏈。
7. PM 在 Boss 回覆前檢查所有交付物、角色回報與流程遵守情況。
8. Boss 整合結果並回覆完成、部分完成或無法完成的具體原因。

## Skill 遵守

- required Skill 必須由獲配該 work item 的角色實際讀取與套用，不可只列名稱；Planner 依 candidate 清單選取並列出路徑後，完整讀取在角色分配後進行。
- 較高層級指令與 required Skill 衝突時，角色停止該項工作並回報衝突；Boss 決定採用的規則。
- 安全、可逆、在 scope 內且不改變使用者結果的決定，角色直接處理。第一個命令失敗不是 blocker：先依 `systematic-debugging` 找根因，再試安全替代方案。
- 只在缺少授權或重大產品選擇、破壞性不可逆操作、安全／隱私／金錢風險、無法裁決的高層規則衝突，或安全方案用盡時停下。三個修正假設都失敗時，升級為架構決策。停下時列出原因、證據、已試方案與 exact resume point。
- 每份角色回報都使用以下欄位：

```text
已讀 Skills：
實際套用規則：
規則衝突或缺漏：
沿用的有效做法：
本次教訓：
自主決策與理由：
```

## 等待子代理的活動觀察

Boss 等待子代理時，將 `wait_agent`／`wait_threads` timeout 視為本次觀察窗尚未收到 `final`，不是卡住、失敗或 `BLOCKED`。每次等待返回後，Boss 都從該子代理可用的活動來源讀取新資料，並與上一次 observation cursor／時間戳比對。新 commentary、command/tool start、正在執行、stdout/stderr、exit code、tool result、status、artifact、process 或 log 任一項有新內容或變化時，更新 observation cursor／時間戳並繼續等待。

- 對 Codex thread，先以 `codex_app__wait_threads` 做有界觀察，再以 `codex_app__read_thread` 讀取 recent commentary 與 tool output，然後依差異決定是否繼續等待。
- 對目前沒有中途輸出讀取接口的內部 collaboration agent，`wait_agent` timeout 只能記為「未收到 mailbox/final，活動未可觀測」，並維持等待；不得據此中止。
- 只有已觀察不到新活動、可用來源也驗證沒有 status、artifact、process、log 變化，且同時符合本 Skill 的既有停下條件時，才可停下。停下回報列出原因、證據、已試方案與 exact resume point。

## 跨工作 lessons

- 每個 Git project 使用 `<repo>/.workers-group/lessons.md`。Planner 只在規劃前以已知任務關鍵字做一次有界 `rg -n -i -C 3` 搜尋，並在計畫中寫出沿用做法與避免錯誤；檔案不存在或無相符結果時記錄「沒有相符 lessons」後繼續，不擴大關鍵字、不讀完整檔案、也不掃描更大範圍。
- Executor 只在同一直接交付 work item 內、且擁有該檔案時寫入。沒有可重用教訓就不建檔也不修改；無 Git root 或無 ownership 時，只在回報標示未持久化。
- 只收有證據支持、會改變下次行動的內容；不收 secrets、個資、猜測或一次性細節。同類情況更新既有條目，不重複新增。
- 每條固定使用：

```text
日期與情境：
有效做法：
教訓：
下次預設：
證據：
```

## Boss 真人回覆

Boss 對真人以白話依固定順序回覆：第一行先說結果與影響，接著才說修改、實際驗證、剩餘限制。重要術語第一次出現時，先說白話用途，再保留原名；真人未要求時，不傾倒角色儀式或內部流程。

## PM 檢查

PM 只在兩個節點檢查：Executor 開始前，以及 Boss 回覆前。

PM 不追蹤進度、時間、deadline、ETA、heartbeat 或排程；不重跑測試，也不判斷程式品質。

PM 必須檢查 `沿用的有效做法`、`本次教訓`、`自主決策與理由` 是否具體對應實際工作；空白或泛稱是缺件。PM 只有驗證到缺少交付物、明確流程或 Skill 偏離，或需 Boss 裁決的高層規則衝突時，才提出停止或補正。

PM 回報固定使用：

```text
工作完成度：完成／部分完成／缺少
已完成成果：
缺少成果：
流程遵守：符合／偏離
Skill 遵守：
發現的偏離：
需要補正：
```

PM 發現同一流程缺件或流程偏離時，Boss 只安排一次針對性補正。補正後仍不符合時，Boss 回報部分完成與具體缺口，不再重開同一輪流程；這項限制不限制為找出技術根因所做的除錯。

## Executor 自檢

- 文件或設定變更：執行對應 parser、validator 或格式檢查。
- 程式變更：執行最貼近修改內容的一項現有測試或 build。
- 無法執行：在回報中寫出原因，不得改寫成已通過。
- 自檢由完成該 work item 的 Executor 執行；PM 只檢查自檢結果或原因是否存在。
- 自檢無法執行時，Boss 如實說明該限制並依已完成交付物回覆；不得因此新增確認流程。

## 角色回報

每份回報都列出：

```text
角色：
工作結果：完成／部分完成／無法完成
owned files：
已完成成果：
最低限度自檢：
已讀 Skills：
實際套用規則：
規則衝突或缺漏：
沿用的有效做法：
本次教訓：
自主決策與理由：
```

## 常見錯誤

- 因為趕時間而略過 Planner 或 required Skills：停止並先補齊 work item。
- 讓 PM 追 ETA 或定時催進度：改為在兩個指定節點檢查完成度與流程。
- 用「測過了」取代自檢結果：列出實際命令與結果，或說明無法執行的原因。
- 為了多一層確認而另派人做檢查：停止。自檢只屬於原 work item 的 Executor，PM 只核對回報是否完整。
- 將確認、檢查或報告包裝成新的 work item：停止。work item 必須直接產出使用者要求的交付物。
- 缺件後反覆重開流程：只做一次針對性補正，其後直接回報缺口。
- 第一個命令失敗就停下：先確認錯誤與根因，再試安全替代方案；三個修正假設失敗才升級架構決策。
