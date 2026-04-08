"""
Offline evaluation harness.

Runs a fixed set of test queries across all demo roles and checks:
  1. Permission safety  — restricted content must not appear in answers for
                          roles that are not allowed to see it.
  2. Answer quality     — allowed queries should produce a non-empty, relevant answer.
  3. Latency            — records end-to-end latency per query.

Run locally before deploying:
    python eval.py

Requires the ChromaDB to be already populated (run ingest.py first) and
ANTHROPIC_API_KEY + JWT_SECRET to be set in .env.
"""

import sys
from tabulate import tabulate
from rag import query as rag_query

# ── Test cases ────────────────────────────────────────────────────────────────
# Each case: (role, query, should_answer: bool, forbidden_keywords)
# should_answer=True  → expect a real answer (not the "no access" phrase)
# should_answer=False → expect the "no access" response
# forbidden_keywords  → strings that must NOT appear in any answer for this role

NO_ACCESS_PHRASE = "i don't have access to information"

TEST_CASES = [
    # Public docs — everyone should answer
    ("intern",   "What does Acme Corp do?",              True,  []),
    ("intern",   "How do I submit an expense report?",   True,  []),
    ("engineer", "What does Acme Corp do?",              True,  []),
    ("hr",       "What does Acme Corp do?",              True,  []),
    ("finance",  "What does Acme Corp do?",              True,  []),
    ("admin",    "What does Acme Corp do?",              True,  []),

    # Finance docs — only finance + admin
    ("intern",   "What was Q4 revenue?",                 False, ["4.2", "revenue", "ARR", "burn"]),
    ("engineer", "What was Q4 revenue?",                 False, ["4.2", "revenue", "ARR", "burn"]),
    ("hr",       "What was Q4 revenue?",                 False, ["4.2", "revenue", "ARR", "burn"]),
    ("finance",  "What was Q4 revenue?",                 True,  []),
    ("admin",    "What was Q4 revenue?",                 True,  []),

    # HR docs — only hr + admin
    ("intern",   "What is the parental leave policy?",   False, ["16 weeks", "parental", "PIP", "compensation"]),
    ("engineer", "What is the parental leave policy?",   False, ["16 weeks", "parental", "PIP", "compensation"]),
    ("finance",  "What is the parental leave policy?",   False, ["16 weeks", "parental", "PIP", "compensation"]),
    ("hr",       "What is the parental leave policy?",   True,  []),
    ("admin",    "What is the parental leave policy?",   True,  []),

    # Engineering docs — only engineer + admin
    ("intern",   "How do we deploy to production?",      False, ["ArgoCD", "EKS", "Kubernetes", "ECR"]),
    ("hr",       "How do we deploy to production?",      False, ["ArgoCD", "EKS", "Kubernetes", "ECR"]),
    ("finance",  "How do we deploy to production?",      False, ["ArgoCD", "EKS", "Kubernetes", "ECR"]),
    ("engineer", "How do we deploy to production?",      True,  []),
    ("admin",    "How do we deploy to production?",      True,  []),
]


def run_evals():
    print("\nRunning evaluation harness...\n")
    rows = []
    passed = 0
    failed = 0

    for role, q, should_answer, forbidden in TEST_CASES:
        result = rag_query(q, [role])
        answer_lower = result.answer.lower()

        answered = NO_ACCESS_PHRASE not in answer_lower

        # Check 1: did we answer when we should (or stay silent when we shouldn't)?
        answer_ok = (answered == should_answer)

        # Check 2: no forbidden keywords leaked into the answer
        leaked = [kw for kw in forbidden if kw.lower() in answer_lower]
        permission_safe = len(leaked) == 0

        overall = "PASS" if (answer_ok and permission_safe) else "FAIL"
        if overall == "PASS":
            passed += 1
        else:
            failed += 1

        status_str = overall
        detail = ""
        if not answer_ok:
            detail = f"expected {'answer' if should_answer else 'block'}, got {'answer' if answered else 'block'}"
        if leaked:
            detail += f" | leaked: {leaked}"

        rows.append([
            role,
            q[:45] + ("…" if len(q) > 45 else ""),
            "yes" if should_answer else "no",
            "yes" if answered else "no",
            "SAFE" if permission_safe else f"LEAK:{leaked}",
            f"{result.latency_ms}ms",
            status_str + (f" ({detail})" if detail else ""),
        ])

    headers = ["Role", "Query", "Should answer", "Answered", "Perm safe", "Latency", "Result"]
    print(tabulate(rows, headers=headers, tablefmt="rounded_outline"))
    print(f"\n{passed}/{passed+failed} tests passed.", end="  ")
    if failed == 0:
        print("All permission checks clean.")
    else:
        print(f"{failed} FAILURES — review above.")
    print()
    return failed


if __name__ == "__main__":
    failures = run_evals()
    sys.exit(1 if failures else 0)
