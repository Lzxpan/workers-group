# Acceptance and evidence

每項 acceptance criterion 必須說明可執行檢查、預期結果與 evidence path。證據至少記錄 command、exit code、passed、failed、skipped、時間與 artifact；編譯成功只證明編譯，不證明未執行的 runtime、hardware、browser 或 provider 行為。Waiver 要有 owner、理由、影響與 expiry。

v2 的 `EVIDENCE_REVIEW` 只確認 evidence 是否可讀、可追溯且足以交給下一個驗證 owner；basic 交給 Boss 的 `boss_verification`，strict 交給 QA，兩者都不是單靠狀態字串的完成證明。每次 review 同時標記治理狀態、現行 mechanical status、已驗證事實、假設、推論、失敗與 `NOT VERIFIED` 範圍。技能席產出只能作為建議 evidence，必須由 sponsor 與固定 owner 轉成可執行／可驗收的工作，不能單獨支持放行。

basic 的 Boss verification 至少包含 `verdict: PASS`、`changed_scope_review: PASS`、一項以上 `focused_checks`、可讀 `evidence` 與 `limitations` 陣列。focused check 只證明它實際執行的檢查；沒有實際執行的 runtime、browser、provider、hardware、compute use 或 production 行為必須留在 `limitations` 或 `NOT_VERIFIED`。
