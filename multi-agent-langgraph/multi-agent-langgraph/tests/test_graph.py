import sys, os
from types import SimpleNamespace as NS
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
import graph

class FakeLLM:
    def __init__(self, verdicts): self.v = list(verdicts)
    def invoke(self, prompt):
        if "Review the draft" in prompt:
            return NS(content='{"verdict":"%s","feedback":"be clearer"}' % self.v.pop(0))
        return NS(content="text")

def test_approve_first_time():
    out = graph.build_graph(FakeLLM(["approve"])).invoke({"task": "t", "rejections": 0, "log": []})
    assert out["status"] == "approved" and out["rejections"] == 0

def test_one_rejection_then_approve():
    out = graph.build_graph(FakeLLM(["reject", "approve"])).invoke({"task": "t", "rejections": 0, "log": []})
    assert out["status"] == "approved" and out["log"].count("reviewer: reject") == 1

def test_reject_twice_escalates():
    out = graph.build_graph(FakeLLM(["reject", "reject"])).invoke({"task": "t", "rejections": 0, "log": []})
    assert out["status"] == "escalated" and out["rejections"] == 2
