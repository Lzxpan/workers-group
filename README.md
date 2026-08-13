# 打工人集團

`orchestrating-workers-group` 是讓 Codex 處理複雜工作時，有清楚分工、最小驗證與可交付結果的協作 Skill。

![四名成員圍著任務看板協作，依序把規劃、實作與交付串起來。](assets/workers-group-four-role-overview.png)

## 適用情況

適合多步驟、需要多人角色分工，或真人明確要求協作流程的工作。單一小修改或單純問答通常不需要啟用。

## 四個角色

- Boss：唯一直接與真人溝通的人，負責確認目標、挑選適用 Skills、分派工作並整合結果。
- `workers_planner`：把目標拆成可直接交付的 work items，清楚標明檔案 ownership、完成條件與 `required_skills`。
- `workers_pm`：只在執行前與 Boss 回覆前，檢查成果是否齊全，以及流程和 Skills 是否照規則執行。
- `workers_executor`：只修改指派的檔案，完成後執行一項最貼近內容的自檢。

## 特色

- 四個角色各有邊界，避免多人同時改同一個檔案。
- 規劃先寫清楚 ownership 與完成條件，讓交付可以直接驗收。
- 每個 Executor 只做一項貼近修改內容的自檢，沒有可跑的檢查就如實說明。
- 角色回報固定包含已讀 Skills、實際套用規則、衝突或缺漏、可沿用做法、教訓與自主決策。

## 安裝與使用

1. 複製這個 repository 到 Codex 的 Skills 目錄，例如 `C:\Users\<user>\.codex\skills\orchestrating-workers-group`。
2. 保留 `SKILL.md` 與 `agents/openai.yaml` 的相對位置；需要專用角色設定時，一併採用 `.codex/agents/` 的三個 TOML 檔。
3. 重啟 Codex，讓新的 Skill 與角色設定載入。
4. 對複雜任務啟用 `$orchestrating-workers-group`，由 Boss 依 `SKILL.md` 建立規劃、分派與最終交付。

## 工作流程

```mermaid
flowchart LR
    U[真人提出目標] --> B[Boss 確認目標與 Skills]
    B --> P[workers_planner 建立 direct-delivery work items]
    P --> M[workers_pm 檢查 ownership、完成條件與 required_skills]
    M --> E[workers_executor 只改 owned files 並自檢]
    E --> M2[workers_pm 檢查成果與流程]
    M2 --> B2[Boss 整合並回覆真人]
```

## 版本歷程

### 2026-08-13

- 公開內容改為目前的四角色協作模型：Boss、`workers_planner`、`workers_pm`、`workers_executor`。
- 移除不屬於現行公開套件的舊目錄與素材，讓安裝內容只保留需要的 manifest 檔案。
- 新增公開 README 概覽圖與繁體中文使用說明。

## 授權與安全

本專案採用 [MIT License](LICENSE)。如發現安全問題，請依 [SECURITY.md](SECURITY.md) 的方式私下回報。
