from datetime import date
from decimal import Decimal
from pathlib import Path

from src import refdata
from src.deterministic_checker import check_unbundling
from src.models import BillLine

FIXTURE = Path(__file__).parent / "fixtures" / "cms_ptp_sample.csv"


def _ref():
    return refdata.load_files([FIXTURE])


def _line(n, code, mods=(), d="2026-08-14", amount="100.00"):
    return BillLine(line_no=n, code=code, description=code, date=d, amount=Decimal(amount),
                    modifiers=tuple(mods))


def test_cms_file_parses_past_the_copyright_header():
    ref = _ref()
    assert len(ref) == 5
    e = ref.ptp_edit("80048", "80053")  # either order
    assert e and e.column1 == "80053" and e.column2 == "80048" and e.modifier_indicator == "1"
    assert e.effective == date(1996, 1, 1) and e.deletion is None


def test_deleted_edits_only_apply_before_the_deletion_date():
    ref = _ref()
    assert ref.ptp_edit("22222", "33333", date(2024, 6, 1)) is not None
    assert ref.ptp_edit("22222", "33333", date(2026, 8, 14)) is None


def test_bypass_modifier_clears_indicator_1_edits():
    ref = _ref()
    plain = [_line(1, "80053"), _line(2, "80048")]
    with_59 = [_line(1, "80053"), _line(2, "80048", mods=["59"])]
    assert len(check_unbundling(plain, ref)) == 1
    assert check_unbundling(with_59, ref) == []


def test_indicator_0_edits_cannot_be_bypassed():
    ref = _ref()
    found = check_unbundling([_line(1, "99999"), _line(2, "11111", mods=["59"])], ref)
    assert len(found) == 1 and "even with a modifier" in found[0].question


def test_indicator_9_and_different_dates_produce_nothing():
    ref = _ref()
    assert check_unbundling([_line(1, "44444"), _line(2, "55555")], ref) == []
    assert check_unbundling([_line(1, "80053", d="2026-08-14"),
                             _line(2, "80048", d="2026-08-15")], ref) == []


def test_carc_lookup_accepts_group_prefix_or_bare_code():
    ref = refdata.load_demo()
    assert "Contractual" in ref.carc("co-45")
    assert ref.carc("ZZ-999") is None
