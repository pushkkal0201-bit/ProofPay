"""Bounded, read-only investigation with explicit provider selection."""
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


def configuration():
    model = os.environ.get("PROOFPAY_MODEL", "").strip()
    provider = os.environ.get("PROOFPAY_PROVIDER", "ollama")
    return dict(model=model or None, provider=provider if model else "policy",
                configured=bool(model) and provider in ("ollama", "openai") and
                (provider != "openai" or bool(os.environ.get("ENGINE_API_KEY"))))


def ask_model(model, messages):
    provider = os.environ.get("PROOFPAY_PROVIDER", "ollama")
    headers = {"Content-Type": "application/json"}
    if provider == "openai":
        key = os.environ.get("ENGINE_API_KEY")
        if not key:
            raise ValueError("Missing API credential.")
        endpoint = "https://api.openai.com/v1/chat/completions"
        headers["Authorization"] = "Bearer " + key
        payload = dict(model=model, messages=messages, temperature=0.15,
                       response_format={"type":"json_object"}, store=False)
    elif provider == "ollama":
        endpoint = "http://127.0.0.1:11434/api/chat"
        payload = dict(model=model, messages=messages, stream=False, format="json",
                       options={"temperature":0.15})
    else:
        raise ValueError("Unknown inference provider.")
    req = Request(endpoint, data=json.dumps(payload).encode(), headers=headers)
    with urlopen(req, timeout=120) as res:
        body = json.loads(res.read(262144))
    message = body["choices"][0]["message"] if provider == "openai" else body["message"]
    return json.loads(message["content"])


def suggest(case, report):
    options = ["check_source", "check_ledger", "check_contract"]
    if report["draft"]:
        options.append("review_draft")
    model = os.environ.get("PROOFPAY_MODEL", "").strip()
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
        "read_ledger": report["LEDGER_SUMMARY"],
        "read_evidence": [dict(line=p["line"], clause=p["clause"], gaps=p["gaps"],
                               references=[e["id"] for e in p["anchors"]],
                               milestones=p["truth_table"],
                               submitted_records=[dict(id=e.id, kind=e.kind, quantity=e.quantity,
                                                       verified=e.verified, timestamp=e.timestamp.isoformat())
                                                  for e in case.evidence if e.line == p["line"]
                                                  and e.invoice == case.invoice]) for p in report["proof"]],
        "read_gst": dict(master_match=report["master_match"], statement=report["statement"],
                         itc_review=report["itc_review"], adjusted_split=report["LEDGER_SUMMARY"]["adjusted_tax_split"]),
    }
    system = (Path(__file__).resolve().parents[1] / "system_prompt.txt").read_text(encoding="utf-8")
    facts = dict(state=report["state"], reasons=report["reasons"], objection=case.dispute_text,
                 allowed_tasks=options, tools=list(views))
    messages = [{"role":"system","content":system}, {"role":"user","content":json.dumps(facts)}]
    trace = []
    for _ in range(len(views)+1):
        decision = ask_model(model, messages)
        if not isinstance(decision,dict):
            raise ValueError("Expected an action object.")
        if set(decision) == {"task"} and trace and decision["task"] in options:
            return dict(mode=model, provider=os.environ.get("PROOFPAY_PROVIDER", "ollama"),
                        task=TASKS[decision["task"]], trace=trace,
                        inspections=[dict(tool=name, result=views[name]) for name in trace])
        tool = decision.get("tool")
        if set(decision) != {"tool"} or tool not in views or tool in trace:
            raise ValueError("Expected an unused inspection tool or a valid final task.")
        trace.append(tool)
        messages.extend([{"role":"assistant","content":json.dumps(decision)},
                         {"role":"user","content":json.dumps({"result":views[tool]})}])
    raise ValueError("Investigation step budget exhausted.")
