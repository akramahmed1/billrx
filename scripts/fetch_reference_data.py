"""Download CMS NCCI procedure-to-procedure (PTP) edit files and convert them to
the CSV format src/refdata reads.

CMS publishes the files quarterly as ZIP archives on the NCCI pages
(https://www.cms.gov/medicare/coding-billing/national-correct-coding-initiative-ncci-edits).
Each quarter's URLs change, so pass them explicitly:

  python scripts/fetch_reference_data.py --out refdata/ \
      https://www.cms.gov/files/zip/<practitioner-ptp-edits-part-1>.zip ...

Then point the app at the result:
  BILLRX_NCCI_PTP_CSV=refdata/ptp_part1.csv:refdata/ptp_part2.csv

Archives may contain tab-delimited .txt, .csv or .xlsx (needs openpyxl).
After any CMS layout change, run the tests: parse_cms_ptp() refuses files
without the expected 'Column 1' header instead of loading garbage.
"""
from __future__ import annotations

import argparse
import csv
import io
import sys
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.refdata import parse_cms_ptp  # noqa: E402


def rows_from_member(name: str, data: bytes) -> list[list[str]]:
    lower = name.lower()
    if lower.endswith(".xlsx"):
        from openpyxl import load_workbook  # optional dependency

        wb = load_workbook(io.BytesIO(data), read_only=True)
        return [["" if v is None else str(v) for v in row]
                for ws in wb.worksheets for row in ws.iter_rows(values_only=True)]
    text = data.decode("utf-8", errors="replace")
    delim = "\t" if lower.endswith(".txt") else ","
    return list(csv.reader(io.StringIO(text), delimiter=delim))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("urls", nargs="+")
    ap.add_argument("--out", default="refdata")
    args = ap.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    written = []
    for i, url in enumerate(args.urls, start=1):
        with urllib.request.urlopen(url, timeout=120) as resp:
            blob = resp.read()
        with zipfile.ZipFile(io.BytesIO(blob)) as z:
            members = [m for m in z.namelist() if m.lower().endswith((".txt", ".csv", ".xlsx"))]
            for m in members:
                rows = rows_from_member(m, z.read(m))
                buf = io.StringIO()
                csv.writer(buf).writerows(rows)
                try:
                    edits = parse_cms_ptp(buf.getvalue())
                except ValueError:
                    continue  # readme or other non-edit file in the archive
                path = out / f"ptp_part{i}_{Path(m).stem}.csv"
                path.write_text(buf.getvalue())
                written.append((path, len(edits)))
    for path, n in written:
        print(f"{path}: {n:,} edits")
    if not written:
        print("no PTP edit tables found in the given archives", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
