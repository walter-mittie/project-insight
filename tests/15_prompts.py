import sys, os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.nl2sql import generate_sql
from src.executor import execute_sql
from src.db import get_connection
from datetime import datetime

conn = get_connection()

queries = [
    # Cat 1 — Single-table filter
    (
        "Q01",
        "Cat1 — Single-table filter",
        "How many distinct SKUs were sold in Q1 2024?",
    ),
    (
        "Q02",
        "Cat1 — Single-table filter",
        "What are the top 10 SKUs by net revenue in 2025 for active products only?",
    ),
    (
        "Q03",
        "Cat1 — Single-table filter",
        "What was the total incremental volume from promotional activity in 2024?",
    ),
    # Cat 2 — Aggregation / KPI
    (
        "Q04",
        "Cat2 — Aggregation/KPI",
        "What was total gross revenue and total trade discount by channel in 2025?",
    ),
    (
        "Q05",
        "Cat2 — Aggregation/KPI",
        "What was NitroBoost's volume market share in 2024 by quarter?",
    ),
    (
        "Q06",
        "Cat2 — Aggregation/KPI",
        "What was the price index for the Dairy category across all banners in 2025?",
    ),
    # Cat 3 — Multi-table join
    (
        "Q07",
        "Cat3 — Multi-table join",
        "What was net revenue by region and category in Q4 2025?",
    ),
    (
        "Q08",
        "Cat3 — Multi-table join",
        "For the Grocery channel, what was net revenue and volume market share by brand in 2025?",
    ),
    (
        "Q09",
        "Cat3 — Multi-table join",
        "What was numeric distribution for the Snacks category by banner in 2024?",
    ),
    # Cat 4 — Ambiguous FMCG term
    ("Q10", "Cat4 — Ambiguous FMCG term", "What was total revenue by brand in 2024?"),
    (
        "Q11",
        "Cat4 — Ambiguous FMCG term",
        "What is the market share of the top 3 brands in the Beverages category?",
    ),
    (
        "Q12",
        "Cat4 — Ambiguous FMCG term",
        "What is the average price of Dairy products sold through Tesco?",
    ),
    # Cat 5 — Time-period filter
    (
        "Q13",
        "Cat5 — Time-period filter",
        "Compare total net revenue and volume units by category between 2024 and 2025.",
    ),
    (
        "Q14",
        "Cat5 — Time-period filter",
        "What was total net revenue by channel in January 2025?",
    ),
    (
        "Q15",
        "Cat5 — Time-period filter",
        "What was the weekly trend of volume units for the Confectionery category in H2 2025?",
    ),
]

OUTPUT_PATH = os.path.join(os.path.dirname(__file__), "15_prompts_output.md")

lines = []

lines.append("# 15-Query Manual Test Suite — F-08 AC3")
lines.append(f"\n**Run timestamp:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}  ")
lines.append(f"**Total queries:** {len(queries)}  ")
lines.append(f"**Model:** gemini-2.5-flash  \n")
lines.append("---\n")

for qid, category, question in queries:
    print(f"Running {qid}...", flush=True)

    lines.append(f"## {qid} — {category}")
    lines.append(f"\n**Question:** {question}\n")

    nl2sql_result = generate_sql(question, [])

    if nl2sql_result.get("status") == "error":
        lines.append(f"**NL2SQL STATUS:** ❌ FAILED\n")
        lines.append(f"**Error:** {nl2sql_result.get('error')}\n")
        lines.append("---\n")
        continue

    # Full reasoning — no truncation
    reasoning = nl2sql_result.get("reasoning", "").strip()
    lines.append(f"### Reasoning\n")
    lines.append(f"{reasoning}\n")

    # Full SQL
    sql = nl2sql_result.get("sql", "").strip()
    lines.append(f"### Generated SQL\n")
    lines.append(f"```sql\n{sql}\n```\n")

    # Execute and print full DataFrame
    exec_result = execute_sql(sql, conn)

    lines.append(f"### Execution Result\n")
    if exec_result["status"] == "success":
        lines.append(f"**Status:** ✅ SUCCESS  ")
        lines.append(f"**Rows:** {exec_result['row_count']}  ")
        lines.append(f"**Time:** {exec_result['exec_time_ms']:.1f}ms  \n")
        if exec_result["row_count"] > 0:
            # Full DataFrame as markdown table
            lines.append(exec_result["data"].to_markdown(index=False))
            lines.append("")
        else:
            lines.append("_Query returned 0 rows._\n")
    else:
        lines.append(f"**Status:** ❌ EXECUTION ERROR  ")
        lines.append(f"**Error type:** `{exec_result['error_type']}`  ")
        lines.append(f"**Error message:** {exec_result['error_message']}\n")

    lines.append("---\n")

with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
    f.write("\n".join(lines))

print(f"\nDone. Output written to: {OUTPUT_PATH}")
