"""Model provider abstraction. From commit one, nothing hard-depends on Bedrock.

MODEL_PROVIDER=bedrock -> live Strands agents via BedrockModel.
MODEL_PROVIDER=mock    -> deterministic scripted agents that still call the real
                          lookup tools and emit identical trace events.
                          Used for tests and the offline demo. No AWS needed.
"""
from __future__ import annotations

import os

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass


def get_provider() -> str:
    return os.getenv("MODEL_PROVIDER", "mock").lower()


def get_model_id() -> str:
    return os.getenv("MODEL_ID", "amazon.nova-lite-v1:0")


def build_bedrock_model():
    """Construct a Strands BedrockModel. Raises if boto3/AWS is unavailable."""
    from strands.models import BedrockModel
    return BedrockModel(
        model_id=get_model_id(),
        region_name=os.getenv("AWS_REGION", "us-east-1"),
    )


class ScriptedAgent:
    """Mock-mode agent. Returns scripted decisions but calls the REAL deterministic
    tools, so tool behavior and trace events are exercised without AWS."""

    def __init__(self, name: str, script: dict, emit):
        self.name = name
        self._script = script
        self._emit = emit

    def review(self, finding_id: str, tools: dict, bill_text: str) -> dict:
        """Run the scripted tool-calling sequence for one candidate finding."""
        steps = self._script[finding_id]
        tools_called = []
        for tool_name, kwargs in steps["tool_calls"]:
            self._emit(self.name, "tool", f"calling {tool_name}({kwargs})")
            result = tools[tool_name](**kwargs, bill_text=bill_text) \
                if tool_name == "inspect_evidence" else tools[tool_name](**kwargs)
            tools_called.append(tool_name)
            self._emit(self.name, "tool", f"{tool_name} returned: {str(result)[:160]}")
        self._emit(self.name, "decision",
                   f"{finding_id}: {steps['verdict']} - {steps['reason'][:120]}")
        return {"verdict": steps["verdict"], "reason": steps["reason"],
                "tools_called": tools_called}
