# Learning and skill evolution

本文件定義從工作 evidence 到可治理改善的閉環。目標是保留可重用、已遮蔽且可追溯的經驗；它不是讓任何角色自動改規則、激活記憶或訓練模型的捷徑。

## Required lifecycle

1. **Evidence**：由實際工作、會議、驗證、failure 或 feedback 產生可讀、Repository 內的 evidence。先區分 verified fact、assumption、inference、failure 與 `NOT_VERIFIED`。
2. **Redaction**：移除 secrets、credentials、私人資料、未經授權的外部內容與不必要細節；保留能支持學習結論的 provenance、範圍與限制。
3. **`CANDIDATE`**：透過 `memory_guard.py` 以候選狀態保存，連結 evidence path 和必要 metadata。任何角色都可提出 candidate，但不能自行升級。
4. **Authorized review**：Boss 或符合 [memory-architecture.md](memory-architecture.md) 條件的 QA reviewer 檢查相關性、redaction、證據綁定、衝突、sensitivity 與可重用性，產生結構化 reviewer artifact。
5. **`ACTIVE`**：只有 reviewer artifact 將 `memory_id`、授權 reviewer、`APPROVED` 或相容的 QA `PASS` verdict 與正確 evidence 精確綁定後才可 activation；缺件、衝突或無法驗證時維持 `CANDIDATE`、標記其他狀態或拒絕。
6. **Retrieval and feedback**：Planner 或適當角色檢索 `ACTIVE` memory，記錄採用／拒絕／過時原因與結果。retrieval 不覆蓋當前 evidence、版本控制、Task Charter 或真人指示。
7. **Skill Doctor proposal**：只有重複、有 evidence 的改善需求才可形成結構化 proposal；它要含 risk classification、failing baseline、target、backup、expected SHA-256、validation 與 rollback，並受 [self-improvement-policy.md](self-improvement-policy.md) 約束。
8. **Human approval for HIGH risk**：QA、evidence、security、sandbox、network、刪除、指揮鏈與本政策相關提案一律停在 `AWAITING_HUMAN_APPROVAL`。未取得明確核准不得 apply；LOW risk 也必須完整驗證、獨立 QA `PASS` 與 Boss review。

## Role responsibilities at the boundaries

- `workers_executor` 保存實作 evidence，提出 sanitized candidate；不 activation、不自改 Skill。
- `workers_qa` 獨立驗證 evidence 範圍，必要時提供 reviewer artifact；不讓 QA verdict 外溢成未跑環境的證明。
- `workers_planner` 在規劃前檢索少量相關 `ACTIVE` memory，對採用與拒絕負責。
- `workers_pm` 維護 candidate／review／proposal 的狀態與 evidence path，阻止無 evidence 的轉換。
- `workers_boss` 確認授權、整合學習的影響並在 HIGH risk 提案等待真人；不以 Boss 身分跳過記憶或 Skill Doctor guard。

## Memory and Skill boundaries

Memory 是可衰退、可衝突、需驗證的工作知識，不是命令來源。當 current source、Task Charter、真人指示或 repository policy 不一致時，記錄衝突並以較高權威／較新 evidence 處理。`CANDIDATE`、高 score、retrospective decision、positive QA 結果與 proposal 存在，均不等於 `ACTIVE` memory 或獲准 Skill 變更。

Skill Doctor 只處理結構化 `propose`、`simulate`、`apply`、`rollback`，不能接收 arbitrary code、shell 或自由格式 patch。若實作失敗或 invariants 不通過，依政策 rollback 並保存 rejected fingerprint；不得以手動直接修改核心 Skill 繞過流程。

## Model-training boundary

此治理 learning 與 model fine-tuning 是兩件事。Hugging Face model training **不會自動觸發**，也不會因 memory、scorecard、meeting、retrospective、Skill Doctor proposal 或 `ACTIVE` activation 而提交 training job。

任何 Hugging Face training 都需要另行、明確的人類授權，並在開始前定義：授權 dataset 與資料處理界線、evaluation protocol、cost／hardware decision、token scope、privacy／license review、失敗／rollback 處理，以及 Hub persistence plan。沒有這些獨立決定時，團隊只可保存治理 evidence 與提出問題，不能下載資料、啟動訓練、花費額度、建立 Hub repository 或發布 model artifact。

## Closure

每個 learning item 要嘛有可讀 reviewer artifact 與目前狀態，要嘛明確記為「沒有可保存內容」。停止時留下 evidence、未驗證邊界與精確 resume point。只有已獲核准且實際驗證的 Skill Doctor operation 才能更改允許的 target；所有其他學習都停在記錄、review 或 proposal 階段。

## `TRAINING_CANDIDATE` 與 `TRAINING_PROPOSAL`

`TRAINING_CANDIDATE` 是本機、內部的能力缺口計數 record，絕不是 external readiness path。它只可在同一明確能力缺口於最近**最多 10 件已驗證任務**中至少出現 3 次時建立；每次出現都要有可讀 evidence、scope 與反例。`BLOCKED`、未驗證、單次失敗、私人推測或未經去識別的內容不得湊數。`TRAINING_CANDIDATE` **完全不包含** training data、案例內容、upload、training job、Hub、credential 或任何外部持久化設定，也不能授權蒐集它們。

只有在需要請真人評估某個已存在的 `TRAINING_CANDIDATE` 時，才可另建獨立的 `TRAINING_PROPOSAL`。proposal 是 human-only review record，不是 external readiness path；它只供人工決策，才可收集逐批、逐項送審的候選案例與審查資訊：用途、來源授權、隱私、去識別、license、evaluation protocol、cost、hardware、model license、Hub visibility、保留期限與 rollback。每項 record 必須標示批准、拒絕或待補件；一項／一批的核准不得外推到下一批、其他用途、其他模型或外部資料。

`TRAINING_PROPOSAL` 仍不是執行授權。不得自動訓練、下載訓練資料、上傳案例、建立 Hugging Face Hub repository、設定 Hub visibility、使用 credential、花費額度或發布 artifact。任何外部提交，包括 training、upload、Hub 動作或 credential 使用，每一次都需要新的明確 HIGH-risk 真人核准，且以該次核准的 scope、token scope、成本／硬體決定、evaluation 與 rollback 為界。兩種 record 都不會繞過 Skill Doctor、資料治理、QA、模型 license 或 human authorization。
