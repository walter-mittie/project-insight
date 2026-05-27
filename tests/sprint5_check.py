import json, pandas as pd
b = json.load(open("docs/benchmark.json"))
assert len(b) == 20
df = pd.read_csv("docs/experiment_results.csv")
assert len(df) == 40
assert df["sql_correct"].notna().all()
assert set(df["condition"].unique()) == {"baseline", "treatment"}
print("Sprint 5 deliverables check: PASS")