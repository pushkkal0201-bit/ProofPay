"""Bounded, read-only investigation using a local Ollama model."""
import json
import os
from pathlib import Path
from urllib.request import Request, urlopen

TASKS = {
    "check_source": "Inspect the original evidence for the flagged line.",
    "check_ledger": "Compare postings with the accounts ledger.",
    "check_contract": "Read the cited clause and compare its scope with the objection.",
    "review_draft": "Review the proposed wording and deadline.",
}


def ask_model(model, messages):
    payload = dict(model=model, stream=False, format="json", options={"temperature": 0},
                   messages=messages)
    req = Request("http://127.0.0.1:11434/api/chat", data=json.dumps(payload).encode(),
                  headers={"Content-Type": "application/json"})
    with urlopen(req, timeout=25) as res:
        return json.loads(json.loads(res.read(262144))["message"]["content"])


def suggest(case, report):
    options = ["check_source", "check_ledger", "check_contract"]
    if report["draft"]:
        options.append("review_draft")
    model = os.environ.get("PROOFPAY_MODEL")
    if not model:
        if report["draft"]:
            choice = "review_draft"
        elif any(p["gaps"] for p in report["proof"]):
            choice = "check_source"
        elif report["reasons"] or report["balance"] <= 0:
            choice = "check_ledger"
        else:
            choice = "check_contract"
        return dict(mode="policy", task=TASKS[choice], trace=["recovery_policy"])

    views = {
        "read_ledger": dict(matrix=report["matrix"], balance=report["balance"]),
        "read_evidence": [dict(line=p["line"], clause=p["clause"], gaps=p["gaps"],
                               references=[e["id"] for e in p["anchors"]]) for p in report["proof"]],
        "read_gst": dict(master_match=report["master_match"], statement=report["statement"],
                         itc_review=report["itc_review"]),
    }
    system = (Path(__file__).resolve().parents[1] / "SYSTEM_PROMPT.md").read_text(encoding="utf-8")
    facts = dict(state=report["state"], reasons=report["reasons"], objection=case.dispute_text,
                 allowed_tasks=options, tools=list(views))
    messages = [{"role":"system","content":system}, {"role":"user","content":json.dumps(facts)}]
    trace = []
    for _ in range(len(views)+1):
        decision = ask_model(model, messages)
        if not isinstance(decision,dict):
            raise ValueError("Expected an action object.")
        if set(decision) == {"task"} and trace and decision["task"] in options:
            return dict(mode=model, task=TASKS[decision["task"]], trace=trace)
        tool = decision.get("tool")
        if set(decision) != {"tool"} or tool not in views or tool in trace:
            raise ValueError("Expected an unused inspection tool or a valid final task.")
        trace.append(tool)
        messages.extend([{"role":"assistant","content":json.dumps(decision)},
                         {"role":"user","content":json.dumps({"result":views[tool]})}])
    raise ValueError("Investigation step budget exhausted.")
