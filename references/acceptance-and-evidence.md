# Acceptance and evidence

每項 acceptance criterion 必須說明可執行檢查、預期結果與 evidence path。證據至少記錄 command、exit code、passed、failed、skipped、時間與 artifact；編譯成功只證明編譯，不證明未執行的 runtime、hardware、browser 或 provider 行為。Waiver 要有 owner、理由、影響與 expiry。

v2 的 `EVIDENCE_REVIEW` 只確認 evidence 是否可讀、可追溯且足以交給 QA；它不是 QA `PASS`。每次 review 同時標記治理狀態、現行 mechanical status、已驗證事實、假設、推論、失敗與 `NOT VERIFIED` 範圍。技能席產出只能作為建議 evidence，必須由 sponsor 與固定 owner 轉成可執行／可驗收的工作，不能單獨支持放行。
