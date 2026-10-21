"""Planner -> Worker -> Reviewer, with a reviewer->worker rework loop and an escalate exit."""
import json, operator, os
from typing import Annotated, TypedDict
from langgraph.graph import StateGraph, START, END

MODEL = os.getenv("MODEL", "claude-sonnet-5-5")
MAX_REJECTIONS = 2


class State(TypedDict):
    task: str
    plan: str
    draft: str
    feedback: str
    verdict: str            # "approve" | "reject"
    rejections: int
    status: str             # "approved" | "escalated"
    log: Annotated[list, operator.add]   # reducer: nodes append, never overwrite


def build_graph(llm):
    def ask(prompt):
        return llm.invoke(prompt).content

    def planner(s):
        plan = ask(f"Break this task into 3-5 short steps for a writer.\nTask: {s['task']}")
        return {"plan": plan, "log": ["planner: plan written"]}

    def worker(s):
        extra = f"\nReviewer feedback to address:\n{s['feedback']}\nPrevious draft:\n{s['draft']}" if s.get("feedback") else ""
        draft = ask(f"Task: {s['task']}\nPlan:\n{s['plan']}{extra}\nWrite the deliverable.")
        return {"draft": draft, "log": [f"worker: draft v{s.get('rejections', 0) + 1}"]}

    def reviewer(s):
        raw = ask('Review the draft against the task. Reply ONLY JSON: {"verdict":"approve"|"reject","feedback":"..."}\n'
                  f"Task: {s['task']}\nDraft:\n{s['draft']}")
        try:
            r = json.loads(raw[raw.index("{"): raw.rindex("}") + 1])
            verdict = r["verdict"] if r["verdict"] in ("approve", "reject") else "reject"
            fb = r.get("feedback", "")
        except Exception:  # unparseable review counts as a reject, never a silent pass
            verdict, fb = "reject", "Reviewer output was not valid JSON; tighten the draft and clarity."
        rej = s.get("rejections", 0) + (verdict == "reject")
        return {"verdict": verdict, "feedback": fb, "rejections": rej, "log": [f"reviewer: {verdict}"]}

    def escalate(s):
        return {"status": "escalated",
                "log": [f"escalate: rejected {s['rejections']}x, returning last draft flagged for human review"]}

    def accept(s):
        return {"status": "approved", "log": ["accept: approved"]}

    def route(s):   # the conditional edge: a real three-way decision
        if s["verdict"] == "approve":
            return "accept"
        return "escalate" if s["rejections"] >= MAX_REJECTIONS else "worker"

    g = StateGraph(State)
    for name, fn in [("planner", planner), ("worker", worker), ("reviewer", reviewer),
                     ("accept", accept), ("escalate", escalate)]:
        g.add_node(name, fn)
    g.add_edge(START, "planner")
    g.add_edge("planner", "worker")
    g.add_edge("worker", "reviewer")
    g.add_conditional_edges("reviewer", route, {"accept": "accept", "worker": "worker", "escalate": "escalate"})
    g.add_edge("accept", END)
    g.add_edge("escalate", END)
    return g.compile()


def run(task, llm=None):
    if llm is None:
        from langchain_anthropic import ChatAnthropic
        llm = ChatAnthropic(model=MODEL)
    return build_graph(llm).invoke({"task": task, "rejections": 0, "feedback": "", "draft": "", "log": []})


if __name__ == "__main__":
    import sys
    out = run(" ".join(sys.argv[1:]) or "Write a 150-word explainer on what an MCP server is.")
    print("\n".join(out["log"]), "\n\nSTATUS:", out["status"], "\n\n", out["draft"])
