"""Render the synthetic demo bill as test uploads: a text PDF, a photo-like PNG,
and an image-only ("scanned") PDF. Run: python scripts/make_intake_fixtures.py
Requires reportlab and Pillow (dev dependencies)."""
from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "tests" / "fixtures"


def bill_rows(bill: dict) -> list[str]:
    rows = [
        "Mercy General Hospital (fictional) - ITEMIZED STATEMENT",
        "Patient: Jordan Ellis (fictional)   Account: 448812",
        "123 Main St, Springfield IL 62701",
        f"Date of service: 08/14/2026",
        "",
        "Line  Date        Code   Description                         Units  Charge",
    ]
    for ln in bill["lines"]:
        y, m, d = ln["date"].split("-")
        rows.append(f"{ln['line_no']}  {m}/{d}/{y}  {ln['code']}  {ln['description']}  1  "
                    f"${Decimal(ln['amount']):,.2f}")
    rows += ["", f"Total charges ${Decimal(bill['statement_total']):,.2f}",
             "Insurance adjustments $5,358.00",
             f"Balance due ${Decimal(bill['statement_balance_due']):,.2f}",
             "SYNTHETIC DATA - ENTIRELY FICTIONAL"]
    return rows


def write_pdf(rows: list[str], path: Path) -> None:
    c = canvas.Canvas(str(path), pagesize=letter)
    y = 740
    c.setFont("Helvetica", 10)
    for r in rows:
        c.drawString(40, y, r)
        y -= 16
    c.save()


def write_png(rows: list[str], path: Path) -> Image.Image:
    font = None
    for cand in ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
                 "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf"):
        if Path(cand).exists():
            font = ImageFont.truetype(cand, 30)
            break
    font = font or ImageFont.load_default()
    img = Image.new("L", (2200, 60 + 48 * len(rows)), 255)
    draw = ImageDraw.Draw(img)
    for i, r in enumerate(rows):
        draw.text((40, 30 + 48 * i), r, fill=0, font=font)
    img.save(path)
    return img


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    bill = json.loads((ROOT / "data" / "synthetic_bill.json").read_text())
    rows = bill_rows(bill)
    write_pdf(rows, OUT / "itemized_bill.pdf")
    img = write_png(rows, OUT / "itemized_bill_photo.png")
    img.convert("RGB").save(OUT / "itemized_bill_scanned.pdf", resolution=200)
    print("wrote", sorted(p.name for p in OUT.iterdir()))


if __name__ == "__main__":
    main()
