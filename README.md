# 打工人集團

> 把複雜任務做成可交接、可驗證、有人負責的協作流程。

`orchestrating-workers-group` 是給 Codex 使用的協作 Skill。它把一件需要多人分工的工作，拆成規劃、執行、證據與獨立 QA（品質驗證）四個可追蹤的階段；最後只有通過驗收的結果才能結案。

## 功能與用途

- **先釐清再動工**：由 Boss 對齊目標、交付物、授權範圍與成功條件。
- **固定分工、責任明確**：Planner、PM、Executor、QA 各自負責規劃、推進、實作與獨立驗證。
- **以證據取代口頭完成**：執行指令、輸出與驗收結果會成為可讀的 evidence（證據）。
- **獨立 QA 閘門**：QA 在唯讀邊界重跑驗證；沒有 `PASS` 與 evidence，不能宣告完成。
- **誠實標示邊界**：沒實際跑過的 browser、provider、hardware 或外部服務，一律保留 `NOT VERIFIED`，不把 build 成功說成正式環境成功。
- **支援長任務治理**：透過 Task Charter、會議紀錄、狀態機、memory 與 Hook，讓多階段任務可追溯、可續作。

## 重要說明

- 這個 repository 是目前全域 `orchestrating-workers-group` 的**技能本體來源**，不包含自動安裝器、外部帳號設定或完整 runtime。
- 請只在複雜、多階段、高風險，或明確需要規劃、實作與 QA 分離的工作中啟用；單行低風險修改或一般問答不需要強制啟動。
- 真實憑證、不可逆資料變更、外部帳號／費用與重大產品方向，仍必須由真人明確核准。
- 此 Skill 的規則不會替代專案既有的 `AGENTS.md`、安全政策或使用者指示；衝突時應先停下並說明。

## 安裝方式

此 repository 沒有自動安裝腳本。若你的 Codex 環境已具備對本機 Skill 的發現與執行支援，可依環境既有的部署流程將整個目錄放到 Skill 根目錄下，例如：

```text
<CodexHome>/skills/orchestrating-workers-group/
├── SKILL.md
├── agents/
├── assets/
├── references/
├── scripts/
└── tests/
```

安裝前請先確認目標環境的變更管理與核准流程；不要直接覆蓋正在使用的版本。此 repository 未提供或設定任何全域 Hook、帳號憑證或 host runtime。

## 使用教學

### 1. 判斷是否該啟用

適合：跨模組改動、需要多人角色分工、風險高、要保留證據，或使用者明確指定本 Skill 的任務。

不必啟用：單純問答、拼字修正、單行低風險調整，或不需要獨立 QA 的小工作。

### 2. 在任務開頭明確呼叫

```text
$orchestrating-workers-group

請把匯出流程改為可重試，保留舊資料格式；請先規劃、實作、做獨立 QA，並附上可重跑的驗證證據。
```

### 3. 期待的工作節奏

1. Boss 建立 Task Charter，確認目標、範圍、風險與驗收條件。
2. Planner 制定可驗收計畫，並由 Executor 與 QA 分別檢查可行性與可測性。
3. PM 維護狀態、角色分工與檔案所有權，避免多人同時修改同一檔案。
4. Executor 進行最小安全實作，保存指令、輸出與產物 evidence。
5. QA 以獨立、唯讀方式重新驗證；失敗就帶著 evidence 回到執行階段。
6. Boss 只回報實際驗證過的範圍，並以 `CLOSED`、`BLOCKED`、`FAILED` 或 `NOT VERIFIED` 清楚交代結果。

## 文件結構

```text
.
├── SKILL.md       # 啟動條件、協作規則與階段導讀
├── agents/        # Codex 介面描述
├── assets/        # Task Charter、QA report、會議與 memory 模板
├── references/    # 角色、流程、證據、Hook 與治理規範
├── scripts/       # 狀態、報告、會議與 Skill Doctor 的驗證工具
└── tests/         # 對核心治理規則的自動化測試
```

## 工作流程架構

```mermaid
flowchart LR
    A[任務與授權] --> B[Task Charter 與 kickoff]
    B --> C[規劃與可測性審查]
    C --> D[實作與 evidence]
    D --> E[獨立 QA]
    E -->|PASS| F[Boss 交付結果]
    E -->|需要修正| D
```

這個流程的關鍵不是增加角色數量，而是讓每個結論都能回到負責人與可重跑的證據。

## 版本歷程

- 2026-08-02：整理為僅保留目前全域 Skill 本體的公開內容，並新增 GitHub README。

## 版權與授權

此 repository 目前未附 `LICENSE` 檔案。使用、複製或再發布前，請先向 repository 維護者確認授權範圍。
