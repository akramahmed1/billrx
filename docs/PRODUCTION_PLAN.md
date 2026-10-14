# BillRx: production plan

Markets: B2B (independent patient advocates first, then employers and benefits
brokers) and B2C (consumers), served by one engine and one multi-tenant data
model: a consumer gets a personal workspace, a practice or employer gets a
shared one.

Principles that do not change:
- The model never calculates money. Arithmetic and code-pair logic are
  deterministic and tested.
- AI reviews evidence and drafts language. Every decision must call a lookup
  tool, and nothing is sent without a human approval record.
- Uploaded documents are untrusted data, never instructions.
- PHI stays in the fewest places possible and never in logs or the audit trail.

## Phase 1: production foundation (this PR)

**Bill intake (new).** `src/intake/` turns an uploaded PDF, scanned PDF or phone
photo into structured line items: PDF text layer first, Tesseract OCR for scanned
pages and images, rule-based parsing (no model reads the document). Each result
is a draft: confidence per line, OCR lowers confidence, unreadable money lines
are surfaced instead of dropped, line items are reconciled against the printed
total, summary bills get a "request an itemized bill" warning. The audit refuses
to run until a person confirms the lines. Limits: 15 MB, 30 pages, PDF/PNG/JPEG/
TIFF by magic bytes.

**Real reference data (new).** `src/refdata/` reads CMS NCCI procedure-to-procedure
edit files (`scripts/fetch_reference_data.py`) with effective and deletion dates,
modifier indicators 0/1/9 and NCCI bypass modifiers. The checker and the Reviewer's
lookup tool share one source, so hypothesis and evidence cannot disagree. The demo
tables remain the default for the reproducible demo.

**Production fixes.**
- Mock mode crashed on any bill outside the four demo findings. A deterministic
  rule-based reviewer now handles every finding kind with the same tools.
- The appeal letter and totals required demo-only fields (`patient`, `payer`,
  `total_allowed`); real bills crashed the drafter. Fixed with safe defaults.
- Prompt-injection hardening for the live reviewer: bill text is fenced as
  untrusted data, fence-closing tags are stripped, the system prompt forbids
  following instructions inside it, and each finding gets a fresh agent so one
  document cannot steer later verdicts.
- `inspect_evidence` returns the cited lines instead of the first 2,000 characters.

**Multi-tenant database (new).** `db/migrations/0001_tenancy.sql` for Postgres:
organizations (personal, advocate practice, employer), users, roles (owner,
admin, advocate, viewer), clients, cases, documents (object-storage references
with SHA-256), findings, approvals, audit log.
- Row-level security on every tenant table, keyed on `SET LOCAL billrx.user_id`;
  no user in session means no rows.
- Composite foreign keys make cross-tenant references impossible even for code
  that bypasses RLS.
- Approvals must be signed by the current user and can never be edited.
- Append-only audit log written by triggers, recording actor and changed field
  names only (no PHI values); even a superuser cannot edit it.
- Every organization keeps at least one owner.

**Evals (new).** `evals/` has 7 cases (demo, clean bill, modifier bypass, EGD
unbundling, different-day repeats, total mismatch, prompt injection). Mock must
score 100% in CI; run with `MODEL_PROVIDER=bedrock` to score the live model and
save a result file with the model id for run-over-run comparison.

**CI.** Unit, intake (with real OCR), reviewer, tenancy (real Postgres service)
tests and the eval suite on every PR.

## Phase 2: the real application

- FastAPI service over the pipeline; the Streamlit demo stays as the demo.
- Next.js app with two front doors on one backend:
  - **Advocates:** client list, case board, upload, confirm-lines screen,
    findings review, approval, letter export, team roles.
  - **Consumers:** upload, confirm, results, action kit.
- Auth with organizations (Clerk or WorkOS). Postgres (RDS or Supabase) using the
  migration above; uploads in S3 with SSE-KMS, presigned URLs, malware scan.
- EOB intake with the same extract, confirm and reconcile flow.
- Billing: per-seat plans for advocates, per-case action kit for consumers
  (Stripe).

## Phase 3: depth of audit

- Medicare physician fee schedule and hospital price-transparency files for a
  "what is a fair price for this code" reference.
- No Surprises Act checks, charity care (501(r)) screening, medically unlikely
  edit (MUE) unit checks.
- Itemized-bill request letter, appeal deadline tracker, call log.
- Employer channel: aggregate, de-identified savings reporting.

## Compliance track (before any real PHI)

- Business associate agreements with every vendor touching PHI (AWS covers
  Bedrock, S3, RDS under its BAA); no PHI to non-BAA services, including
  analytics and error monitoring (scrub PHI before Sentry).
- HIPAA risk assessment, access reviews, encryption at rest and in transit,
  backup and retention policy, breach response runbook.
- Legal review of state rules on paid medical-bill advocacy and negotiation.
- SOC 2 Type I when employer sales require it.

## AI production standards applied

- Structured outputs, schema-validated; every decision tool-grounded.
- Eval suite gates CI; live-model evals before any model or prompt change ships.
- Tracing of model id, prompt version, tool calls, latency and cost per case;
  per-org cost caps.
- Deterministic fallback when the model fails, already implemented.
