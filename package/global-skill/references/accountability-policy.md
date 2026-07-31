# Accountability policy

報告必須區分：已驗證事實、假設、推論、未驗證與失敗。Executor 不可為自己的工作簽發 QA `PASS`。Boss 若發現缺少 evidence、waiver、授權或獨立 QA，必須回報 `PARTIAL`、`BLOCKED` 或 `FAILED`，不得用模糊完成語句掩蓋缺口。

## 可稽核 scorecard

每個角色以 0 到 5 分記錄下列十項 metrics，且每個角色都必須附可讀 evidence：

- `evidence_accuracy`
- `completeness`
- `honesty`
- `requirement_adherence`
- `test_quality`
- `risk_disclosure`
- `collaboration`
- `efficiency`
- `memory_quality`
- `memory_reuse_accuracy`

`scorecard_store.py --file INPUT --output OUTPUT` 會先依 `scorecard.schema.json` 驗證，再以 atomic replace 保存。相同角色在一份 scorecard 中只能出現一次；分數不等於 QA verdict，也不能繞過 evidence gate。
