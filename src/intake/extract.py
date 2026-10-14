"""Extract itemized-bill line items from an uploaded PDF or image.

Deterministic: text comes from the PDF text layer (pdfplumber) or OCR
(Tesseract) for scanned pages and photos; parsing is rule-based. No model reads
the document here, so nothing in it can act as an instruction.

Every result is a DRAFT. `needs_confirmation` is always True: the user (or
advocate) confirms or corrects each line before the audit runs, and lines the
parser could not read are surfaced, never silently dropped.
"""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from datetime import datetime
from decimal import Decimal
from pathlib import Path

MAX_BYTES = 15 * 1024 * 1024
MAX_PAGES = 30
OCR_DPI = 300

MAGIC = {
    b"%PDF": "pdf",
    b"\x89PNG": "image",
    b"\xff\xd8\xff": "image",
    b"II*\x00": "image",
    b"MM\x00*": "image",
}

MONEY = r"\$?\s?\d{1,3}(?:,\d{3})*\.\d{2}"
MONEY_RE = re.compile(MONEY)
CODE_RE = re.compile(
    r"(?<![\d/.-])(?P<code>\d{5}|[A-V]\d{4})(?![\d/])"
    r"(?:-(?P<mods>[A-Z0-9]{2}(?:[-,][A-Z0-9]{2})*))?"
)
DATE_RE = re.compile(r"\b(\d{1,2}/\d{1,2}/\d{2,4}|\d{4}-\d{2}-\d{2})\b")
LINE_RE = re.compile(rf"(?P<amount>{MONEY})\s*$")
TOTAL_RE = re.compile(r"\b(total charges|statement total|total billed|total)\b", re.I)
BALANCE_RE = re.compile(
    r"\b(balance due|amount due|patient balance|please pay|you owe|patient responsibility)\b",
    re.I)
DOS_RE = re.compile(r"\b(date of service|service date|dos)\b", re.I)


class IntakeError(ValueError):
    """The upload cannot be processed (wrong type, too large, unreadable)."""


@dataclass
class ExtractedLine:
    line_no: int
    code: str
    modifiers: list[str]
    description: str
    date: str | None
    units: int
    amount: str  # decimal string, e.g. "620.00"
    page: int
    confidence: str  # high | medium | low
    source: str  # text | ocr
    raw: str


@dataclass
class ExtractedBill:
    lines: list[ExtractedLine]
    statement_total: str | None
    balance_due: str | None
    date_of_service: str | None
    unparsed: list[dict] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    pages: int = 0
    needs_confirmation: bool = True

    @property
    def line_sum(self) -> Decimal:
        return sum((Decimal(ln.amount) for ln in self.lines), Decimal("0"))

    def to_dict(self) -> dict:
        d = asdict(self)
        d["line_sum"] = str(self.line_sum)
        return d

    def to_bill_json(self, confirmed: bool) -> dict:
        """Pipeline input. Refuses to run on an unconfirmed draft."""
        if not confirmed:
            raise IntakeError("extracted lines must be confirmed by a person before auditing")
        if self.statement_total is None:
            raise IntakeError("statement total is required; enter it from the bill")
        return {
            "date_of_service": self.date_of_service,
            "statement_total": self.statement_total,
            "statement_balance_due": self.balance_due or self.statement_total,
            "lines": [{
                "line_no": ln.line_no, "code": ln.code, "modifiers": ln.modifiers,
                "description": ln.description, "date": ln.date or self.date_of_service,
                "units": ln.units, "amount": ln.amount, "page": ln.page,
            } for ln in self.lines],
            "notice": "Extracted from an uploaded document and confirmed by the user.",
        }


def _to_iso(s: str) -> str | None:
    for fmt in ("%m/%d/%Y", "%m/%d/%y", "%Y-%m-%d"):
        try:
            return datetime.strptime(s, fmt).date().isoformat()
        except ValueError:
            pass
    return None


def _money(s: str) -> str:
    return str(Decimal(s.replace("$", "").replace(",", "").strip()))


def parse_bill_text(pages: list[tuple[str, str]]) -> ExtractedBill:
    """Parse page texts. `pages` is [(text, source)] where source is 'text' or 'ocr'."""
    lines: list[ExtractedLine] = []
    unparsed: list[dict] = []
    warnings: list[str] = []
    total = balance = dos = None

    for page_no, (text, source) in enumerate(pages, start=1):
        for raw in text.splitlines():
            row = " ".join(raw.split())
            if not row:
                continue
            if dos is None and DOS_RE.search(row):
                m = DATE_RE.search(row)
                if m:
                    dos = _to_iso(m.group(1))
            amt = LINE_RE.search(row)
            if not amt:
                continue
            head = row[: amt.start()].rstrip()
            code_m = CODE_RE.search(head)
            if BALANCE_RE.search(row) and not code_m:
                balance = _money(amt.group("amount"))
                continue
            if TOTAL_RE.search(row) and not code_m:
                total = _money(amt.group("amount"))
                continue
            if not code_m:
                unparsed.append({"page": page_no, "raw": row,
                                 "reason": "amount without a recognizable CPT/HCPCS code"})
                continue

            before = head[: code_m.start()].strip()
            after = head[code_m.end():].strip()
            date_m = DATE_RE.search(before) or DATE_RE.search(after)
            line_date = _to_iso(date_m.group(1)) if date_m else None
            if date_m:
                after = after.replace(date_m.group(1), "").strip()
            units = 1
            units_m = re.search(r"\s(\d{1,3})$", " " + after)
            if units_m and int(units_m.group(1)) > 0:
                units = int(units_m.group(1))
                after = after[: units_m.start()].strip()
            mods = re.split(r"[-,]", code_m.group("mods")) if code_m.group("mods") else []
            no_m = re.match(r"^(\d{1,4})\b", before)
            line_no = int(no_m.group(1)) if no_m else len(lines) + 1

            confidence = "high" if line_date else "medium"
            if source == "ocr":
                confidence = {"high": "medium", "medium": "low"}[confidence]
            lines.append(ExtractedLine(
                line_no=line_no, code=code_m.group("code"), modifiers=mods,
                description=after.strip(" -:") or "(no description read)",
                date=line_date, units=units, amount=_money(amt.group("amount")),
                page=page_no, confidence=confidence, source=source, raw=row))

    bill = ExtractedBill(lines=lines, statement_total=total, balance_due=balance,
                         date_of_service=dos or next((ln.date for ln in lines if ln.date), None),
                         unparsed=unparsed, warnings=warnings, pages=len(pages))
    if not lines:
        warnings.append("No line items were recognized. The bill may be a summary bill: "
                        "request an itemized bill from the provider.")
    if total is None:
        warnings.append("No statement total found. Enter it from the bill before auditing.")
    elif lines and bill.line_sum != Decimal(total):
        warnings.append(f"Line items add up to ${bill.line_sum:,.2f} but the statement total "
                        f"reads ${Decimal(total):,.2f}. Check for missed or misread lines.")
    if any(ln.confidence == "low" for ln in lines):
        warnings.append("Some lines were read by OCR with low confidence. Check them carefully.")
    return bill


def _sniff(data: bytes) -> str:
    for magic, kind in MAGIC.items():
        if data.startswith(magic):
            return kind
    raise IntakeError("unsupported file type: upload a PDF, PNG, JPEG or TIFF")


def _ocr(image) -> str:
    import pytesseract

    return pytesseract.image_to_string(image, config="--psm 6")


def extract_bill(path: str | Path) -> ExtractedBill:
    p = Path(path)
    data = p.read_bytes()
    if len(data) > MAX_BYTES:
        raise IntakeError(f"file is larger than {MAX_BYTES // (1024 * 1024)} MB")
    kind = _sniff(data)
    pages: list[tuple[str, str]] = []
    if kind == "pdf":
        import pdfplumber

        with pdfplumber.open(p) as pdf:
            if len(pdf.pages) > MAX_PAGES:
                raise IntakeError(f"PDF has more than {MAX_PAGES} pages")
            for page in pdf.pages:
                text = page.extract_text() or ""
                if len(text.strip()) >= 20:
                    pages.append((text, "text"))
                else:  # scanned page: OCR it
                    img = page.to_image(resolution=OCR_DPI).original
                    pages.append((_ocr(img), "ocr"))
    else:
        from PIL import Image, ImageOps

        with Image.open(p) as im:
            im = ImageOps.exif_transpose(im).convert("L")
            pages.append((_ocr(im), "ocr"))
    return parse_bill_text(pages)
