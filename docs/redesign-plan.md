# BillRx UI Redesign Plan (approved direction: multipage stepper)

## Problem
Single long scroll: landing, agent trace, findings, approval, appeal draft, phone script.
The left trace panel does not scroll with content. A layman reads our working notes
before ever getting an answer. Too much scrolling for a 4 minute demo video.

## Competitor scan (2026-09-14)
- Faircare (Mar 2026): upload bill + EOB, plain language explanations, flagged errors,
  next step guidance. Closest to our space.
- Goodbill / Resolve / fightbills: negotiation for a cut. Resolve claims 95% of cases
  find savings.
- Sheer Health: plain English billing Q&A on connected insurance data.
- Counterforce Health (nonprofit): free AI appeal letters.
- Claimable: appeal letters with hallucination controls, $50 per case.
- NYT (Apr 2026): patients use chatbots for bills, but experts found chatbots sometimes
  give wrong advice on laws and payer rules.
- Our edge, verified: deterministic verification (code checks the money, the model
  never calculates), a Reviewer forced to call lookup tools before judging, a human
  approval gate, and published honest negatives. Nobody shows their math. Nobody shows
  what they checked and dropped.

## Structure: 4 screens, sidebar stepper (st.navigation multipage)
1. **Your case** (what we are doing): summary cards (billed $7,842.00, allowed
   $6,000.00, statement $2,484.00 vs EOB $642.00, difference $1,842.00), one plain
   language line on why, one button: Run the audit. Disclaimer on this screen.
2. **Investigation** (how we are solving): pipeline as 3 status steps
   (Extract, Verify, Review) with checkmarks. Raw trace behind a collapsed
   "Show technical details" expander. Reviewer tool calls as small badges.
   Honest negative card: "Checked and dropped: 36415, no NCCI edit exists."
3. **Findings** (results): one card per finding. Verdict chip
   (Worth asking about / Rejected by reviewer), plain language question, 2 to 3
   lines of key evidence. Checkbox per card: Include in my dispute. Sticky bottom
   bar: "N of 3 selected" + Approve button. Nothing drafted until approval.
4. **Action kit** (next steps): after approval, a modal dialog asks
   "How do you want to contact them?" Email draft / Phone script / Both.
   Scripts render in tabs with copy (code blocks) and download buttons.

## Alerts and notifications
- Toast on audit complete ("Audit complete: 3 of 4 findings worth asking about").
- Toast on packet generation.
- One modal dialog for the email/phone/both choice. Everything else inline.

## Visual system (health fintech: calm, clinical, trustworthy)
- Keep teal/emerald primary, deep navy headers, warm off white background.
- One accent color reserved for dollar figures.
- Cards with soft borders, consistent type scale, no alarming red except the small
  "rejected" chip where red means something.

## Trust layer (verification made visible, not claimed)
- Every dollar figure carries a "checked by code" marker.
- Every finding cites evidence (bill page/line, NCCI, EOB remark code).
- Research prototype disclaimer stays on screen 1.

## Gaps folded in (from review)
1. Navigation guards: cannot reach Findings/Action kit before running the audit.
2. Session state carries result + selections across pages.
3. Verify Streamlit version supports st.dialog / st.toast before building.
4. Copy via code blocks + native download buttons (no native clipboard in Streamlit).
5. Auto advance to screen 4 after approval (st.switch_page).
6. "Start over" reset button on screen 1.
7. Mobile check: sidebar collapses, cards must stack on all 4 screens.
8. Deadline: ~12h to 5pm Pacific. Build A+B first, polish if time remains, protect
   the video recording window. Video script must be rewritten for the new UI.
9. README screenshots refresh after rebuild, if time permits.
10. Rollback is free: current version committed in git.

## Repeat audits (judge runs it 3 to 10 times)
Verified 2026-09-14: two headless mock runs produce byte identical output.
Same inputs, same Decimal math, same scripted reviewer, same 4 verdicts every time.
No API cost in mock mode, no degradation, per browser session state isolation
(judges cannot interfere with each other). "Run it ten times, get the same answer
ten times" is the anti hallucination story. The redesign keeps a clean reset path
so repeated runs start fresh.

## "Manage app" button
Streamlit Community Cloud owner console. Visible only to the logged in app owner.
Judges and viewers never see it. For the demo recording, use an incognito window
(not logged in) and it will not appear.

## Build order
- Phase A: 4 screen structure + guards + sticky approval bar (kills scroll pain).
- Phase B: dialog, toasts, tabbed scripts with copy/download, auto advance.
- Phase C: full visual polish.
Each phase independently shippable. Pipeline, data, numbers, and all 9 tests
stay frozen; presentation layer only.
