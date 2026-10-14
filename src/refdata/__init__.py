"""Reference data: NCCI procedure-to-procedure (PTP) edits and claim adjustment
reason codes (CARC).

One interface, two sources:
  - demo tables (default): the small synthetic set the demo scenario needs
  - real CMS files: set BILLRX_NCCI_PTP_CSV (and optionally BILLRX_CARC_CSV)
    to files fetched with scripts/fetch_reference_data.py

The checker and the Reviewer's lookup tools both read from here, so the
hypothesis and the evidence can never disagree.

NCCI PTP semantics (CMS): the Column 2 code is not separately payable when
billed with the Column 1 code on the same date of service, unless the edit's
modifier indicator allows a bypass:
  "0" = no modifier ever allowed
  "1" = an NCCI-associated modifier (e.g. 59, XE, XS, XP, XU) may bypass it
  "9" = not applicable (edit deleted / historical)
"""
from __future__ import annotations

import csv
import io
import os
from dataclasses import dataclass
from datetime import date
from functools import lru_cache
from pathlib import Path

# Modifiers CMS lists as NCCI-associated for PTP bypass (anatomic and
# distinct-service modifiers).
NCCI_BYPASS_MODIFIERS = frozenset({
    "59", "XE", "XS", "XP", "XU",
    "E1", "E2", "E3", "E4", "FA", "F1", "F2", "F3", "F4", "F5", "F6", "F7", "F8", "F9",
    "TA", "T1", "T2", "T3", "T4", "T5", "T6", "T7", "T8", "T9",
    "LT", "RT", "LC", "LD", "LM", "RC", "RI", "24", "25", "57", "58", "78", "79", "27", "91",
})


@dataclass(frozen=True)
class PTPEdit:
    column1: str  # comprehensive code
    column2: str  # component code (the one not separately payable)
    effective: date
    deletion: date | None
    modifier_indicator: str  # "0" | "1" | "9"
    rationale: str

    def active_on(self, dos: date) -> bool:
        if dos < self.effective:
            return False
        return self.deletion is None or dos < self.deletion


class ReferenceData:
    def __init__(self, ptp: list[PTPEdit], carc: dict[str, str], source: str):
        self.source = source
        self._ptp: dict[tuple[str, str], list[PTPEdit]] = {}
        for e in ptp:
            self._ptp.setdefault((e.column1, e.column2), []).append(e)
        self._carc = {k.upper(): v for k, v in carc.items()}

    def ptp_edit(self, code_a: str, code_b: str, dos: date | None = None) -> PTPEdit | None:
        """The edit between two codes (either order) active on the date of service."""
        a, b = code_a.strip(), code_b.strip()
        for pair in ((a, b), (b, a)):
            for e in self._ptp.get(pair, []):
                if dos is None or e.active_on(dos):
                    return e
        return None

    def carc(self, code: str) -> str | None:
        """Explanation for a CARC like 'CO-45' or a bare reason code like '45'."""
        c = code.strip().upper()
        if c in self._carc:
            return self._carc[c]
        bare = c.split("-", 1)[1] if "-" in c else c
        return self._carc.get(bare)

    def __len__(self) -> int:
        return sum(len(v) for v in self._ptp.values())


# ---------- demo tables (synthetic scope, kept for the reproducible demo) ----------

_DEMO_PTP = [
    PTPEdit("80053", "80048", date(1996, 1, 1), None, "1",
            "Basic Metabolic Panel (80048) is a component of Comprehensive Metabolic "
            "Panel (80053). Billing both together may be unbundling unless a modifier "
            "is documented."),
    PTPEdit("43239", "43235", date(1996, 1, 1), None, "1",
            "Diagnostic EGD (43235) is bundled into EGD with biopsy (43239)."),
]

_DEMO_CARC = {
    "CO-45": "Charge exceeds fee schedule / maximum allowable amount. Contractual "
             "adjustment; not the patient's responsibility.",
    "CO-97": "The benefit for this service is included in the payment/allowance for "
             "another service already adjudicated.",
    "PR-1": "Deductible amount. Patient responsibility.",
    "PR-2": "Coinsurance amount. Patient responsibility.",
    "PR-3": "Copayment amount. Patient responsibility.",
}


def load_demo() -> ReferenceData:
    return ReferenceData(_DEMO_PTP, _DEMO_CARC, source="demo")


# ---------- real CMS files ----------

def _parse_cms_date(s: str) -> date | None:
    s = s.strip()
    if not s or s == "*":
        return None
    return date(int(s[0:4]), int(s[4:6]), int(s[6:8]))


def parse_cms_ptp(text: str) -> list[PTPEdit]:
    """Parse a CMS NCCI PTP edit file exported as CSV.

    CMS files start with copyright/title lines; the table begins at the header
    row whose first cell is 'Column 1'. Expected columns, in order:
    Column 1, Column 2, *, Effective Date, Deletion Date, Modifier, PTP Edit Rationale.
    """
    rows = list(csv.reader(io.StringIO(text)))
    start = next((i for i, r in enumerate(rows) if r and r[0].strip().lower() == "column 1"), None)
    if start is None:
        raise ValueError("not a CMS PTP file: no 'Column 1' header row found")
    edits = []
    for r in rows[start + 1:]:
        if len(r) < 6 or not r[0].strip() or not r[1].strip():
            continue
        if not r[3].strip()[:8].isdigit():
            continue  # continuation/notes rows
        effective = _parse_cms_date(r[3])
        if effective is None:
            continue
        edits.append(PTPEdit(
            column1=r[0].strip(),
            column2=r[1].strip(),
            effective=effective,
            deletion=_parse_cms_date(r[4]),
            modifier_indicator=r[5].strip() or "9",
            rationale=r[6].strip() if len(r) > 6 else "",
        ))
    if not edits:
        raise ValueError("CMS PTP file contained no edits")
    return edits


def parse_carc_csv(text: str) -> dict[str, str]:
    """CSV with columns code,description (e.g. 45,"Charge exceeds fee schedule...")."""
    out = {}
    for r in csv.reader(io.StringIO(text)):
        if len(r) >= 2 and r[0].strip() and r[0].strip().lower() != "code":
            out[r[0].strip().upper()] = r[1].strip()
    return out


def load_files(ptp_paths: list[Path], carc_path: Path | None = None) -> ReferenceData:
    ptp: list[PTPEdit] = []
    for p in ptp_paths:
        ptp += parse_cms_ptp(Path(p).read_text(encoding="utf-8", errors="replace"))
    carc = dict(_DEMO_CARC)
    if carc_path:
        carc.update(parse_carc_csv(Path(carc_path).read_text(encoding="utf-8")))
    return ReferenceData(ptp, carc, source="cms:" + ",".join(Path(p).name for p in ptp_paths))


@lru_cache(maxsize=1)
def get_reference_data() -> ReferenceData:
    """Process-wide reference data: real CMS files if configured, else demo."""
    ptp_env = os.getenv("BILLRX_NCCI_PTP_CSV", "").strip()
    if not ptp_env:
        return load_demo()
    carc_env = os.getenv("BILLRX_CARC_CSV", "").strip()
    return load_files([Path(p) for p in ptp_env.split(os.pathsep) if p],
                      Path(carc_env) if carc_env else None)
