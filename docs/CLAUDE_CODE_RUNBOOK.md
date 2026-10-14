# Claude Code runbook: BillRx Phase 1 (production foundation)

Branch: `claude/p1-production-foundation`. Goal: verify bill intake, reference
data, the reviewer fixes, the multi-tenant schema and the evals on this machine,
open the PR, get CI green, get Akram's approval, merge, and verify the demo still
works. Follow the loop plan → approve → build → verify-live → PR → merge.

## Ground rules

- Stay in scope. Do not apply `db/migrations/0001_tenancy.sql` to any shared or
  production database: there is none yet, and creating one is Phase 2.
- No real patient data anywhere. Test files are synthetic.
- If a test fails, fix the root cause. Never weaken, skip or delete a test or
  lower an eval threshold.
- Never commit `.env`, AWS keys, or eval result files.
- Stop and ask Akram whenever something is ambiguous.

## 1. Plan (show Akram, wait for "go")

Print a short plan of steps 2 to 8 and wait for approval.

## 2. Preflight

```bash
git fetch origin && git checkout claude/p1-production-foundation && git pull
gh auth status                      # logged in as akramahmed1
python3 --version                   # 3.10+
tesseract --version                 # install if missing: brew install tesseract (macOS) or sudo apt install tesseract-ocr
docker --version || psql --version  # need one way to run Postgres 16
```

## 3. Install and test

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt pytest reportlab

# Throwaway Postgres for the tenancy tests (skip if Postgres 16 is already local)
docker run -d --name billrx-pg -e POSTGRES_PASSWORD=postgres -p 55432:5432 postgres:16
export BILLRX_TEST_DATABASE_URL=postgresql://postgres:postgres@127.0.0.1:55432/postgres

MODEL_PROVIDER=mock python -m pytest -q     # expect 37 passed, 0 skipped
MODEL_PROVIDER=mock python -m evals.run_evals --no-save   # 7/7, 100%
```

If the tenancy tests show as skipped, `BILLRX_TEST_DATABASE_URL` or `psql` is
missing: fix that, they must run.

## 4. Manual end-to-end checks

```bash
python - <<'EOF'
from src.intake import extract_bill
for f in ["itemized_bill.pdf", "itemized_bill_scanned.pdf", "itemized_bill_photo.png"]:
    b = extract_bill(f"tests/fixtures/{f}")
    print(f, len(b.lines), "lines, total", b.statement_total, "warnings:", b.warnings)
EOF
MODEL_PROVIDER=mock streamlit run app.py
```

In the Streamlit demo, confirm the original 4-finding demo still works: 3 kept,
venipuncture rejected, $1,842.00 delta, appeal draft and approval gate.

Optional, only if Akram's AWS credentials with Bedrock access are configured:

```bash
MODEL_PROVIDER=bedrock python -m evals.run_evals --min-verdict-accuracy 0.85
```

Report the score, including the `injection_in_description` case. A Bedrock
failure is reported, not hidden, and does not block the merge (mock is the CI
gate).

Commit any fixes with clear messages and rerun step 3.

## 5. Pull request

```bash
git push
gh pr create --base main --head claude/p1-production-foundation \
  --title "Phase 1 production foundation: bill intake, CMS data, multi-tenant DB, evals" \
  --body-file docs/PRODUCTION_PLAN.md
gh pr checks --watch   # must be green (tests incl. Postgres + OCR, evals)
```

## 6. Approval checkpoint (stop here)

Show Akram: test and eval results, CI status, the optional Bedrock eval score,
and a reminder that the compliance track in `docs/PRODUCTION_PLAN.md` must be done
before any real patient data is used. Wait for "approve merge".

## 7. Merge

```bash
gh pr merge --squash --delete-branch
docker rm -f billrx-pg   # clean up the throwaway database
```

## 8. Verify live

Ask Akram whether the demo is deployed anywhere (for example Streamlit Community
Cloud) and where. If it is, confirm the deployed demo shows the same 4-finding
result after the merge. If it is not deployed, say so in the report.

If the deployed demo breaks and cannot be fixed quickly: `git revert` the merge
commit on `main`, push, and tell Akram what failed.

## Done report

PR link, merge commit, test and eval results, CI result, Bedrock eval (if run),
live demo check, and any out-of-scope notes.
