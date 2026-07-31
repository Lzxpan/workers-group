# Intelligence tiers

Boss、Planner 使用 `gpt-5.6-sol xhigh`；PM、QA 使用 `gpt-5.6-sol high`；Executor 使用 `gpt-5.6-terra high`。Sol/Luna fallback 為 `gpt-5.6-terra high`，Terra fallback 為 `gpt-5.6-sol medium`。Fallback 只記錄在 policy，不放進不支援該欄位的 custom agent TOML。
