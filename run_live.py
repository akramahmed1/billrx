"""Headless live-mode runner. Run on a machine with AWS credentials configured:
    python run_live.py
Uses Bedrock-backed Strands agents (MODEL_PROVIDER=bedrock). Falls back to the
deterministic scripted review if the live Reviewer misbehaves.
"""
import os

os.environ.setdefault("MODEL_PROVIDER", "bedrock")
os.environ.setdefault("MODEL_ID", "amazon.nova-lite-v1:0")
os.environ.setdefault("AWS_REGION", "us-east-1")

from src.pipeline import Pipeline

p = Pipeline()
res = p.run("data/synthetic_bill.json", "data/synthetic_eob.json")

print(f"provider: {p.provider}")
print(f"claim delta: ${res.delta}")
for r in res.reviewed:
    c = r.candidate
    print(f"{r.verdict:6} {c.finding_id} tools={r.tools_called}")
    print(f"       reason: {r.reason[:160]}")
print("--- trace ---")
for t in res.trace:
    print(f"{t.seq:02d} [{t.agent}/{t.kind}] {t.text[:110]}")
