"""Unit tests for the Product Master service.
Pure functions only — no DB required.
Run with: cd /app/backend && python -m pytest tests/test_product_master_service.py -q
"""
import io

import pandas as pd
import pytest

from services.product_master import (
    REQUIRED_COLUMNS,
    parse_excel,
    safe_float,
    split_csv_field,
)


def _xlsx(rows):
    df = pd.DataFrame(rows, columns=REQUIRED_COLUMNS)
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as w:
        df.to_excel(w, index=False, sheet_name="Product Master")
    return buf.getvalue()


class TestSplitCsvField:
    def test_basic_comma(self):
        assert split_csv_field("A,B,C") == ["A", "B", "C"]

    def test_semicolon_pipe_newline(self):
        assert split_csv_field("A;B|C\nD") == ["A", "B", "C", "D"]

    def test_trim_dedupe_case_insensitive(self):
        assert split_csv_field(" a , A , b ") == ["a", "b"]

    def test_empty_and_nan(self):
        assert split_csv_field("") == []
        assert split_csv_field(None) == []
        assert split_csv_field(float("nan")) == []

    def test_number_input(self):
        assert split_csv_field(110) == ["110"]


class TestSafeFloat:
    @pytest.mark.parametrize("v, expected", [
        ("110", 110.0),
        ("1,200", 1200.0),
        ("  99.5 ", 99.5),
        (110, 110.0),
        ("", None),
        ("abc", None),
        (None, None),
    ])
    def test_cases(self, v, expected):
        assert safe_float(v) == expected

    def test_nan(self):
        assert safe_float(float("nan")) is None


class TestParseExcel:
    def test_happy_path(self):
        rows, errors = parse_excel(_xlsx([
            ["Account1", "Vertis", "Blue", "IND-3,IND-4", "SKU1,SKU2", 110],
            ["Account2", "Sofia", "White", "IND-5", "SKU9", 130],
        ]))
        assert errors == []
        assert len(rows) == 2
        assert rows[0]["account"] == "Account1"
        assert rows[0]["sizes"] == ["IND-3", "IND-4"]
        assert rows[0]["skus"] == ["SKU1", "SKU2"]
        assert rows[0]["cost"] == 110.0

    def test_missing_required_columns_raises(self):
        df = pd.DataFrame([[1, 2, 3]], columns=["A", "B", "C"])
        buf = io.BytesIO()
        with pd.ExcelWriter(buf, engine="openpyxl") as w:
            df.to_excel(w, index=False)
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as ex:
            parse_excel(buf.getvalue())
        assert ex.value.status_code == 400

    def test_row_validation_errors(self):
        rows, errors = parse_excel(_xlsx([
            ["", "Vertis", "Blue", "S1", "K1", 110],
            ["A", "", "Blue", "S1", "K1", 110],
            ["A", "Vertis", "", "S1", "K1", 110],
            ["A", "Vertis", "Blue", "S1", "K1", "bad"],
            ["A", "Vertis", "Blue", "S1", "K1", -5],
        ]))
        assert rows == []
        assert len(errors) == 5
        assert errors[0]["row"] == 2
        assert any("Account" in e for e in errors[0]["errors"])
        assert any("Cost" in e for e in errors[3]["errors"])
        assert any("negative" in e for e in errors[4]["errors"])

    def test_empty_skus_and_sizes_allowed(self):
        rows, errors = parse_excel(_xlsx([
            ["A1", "Vertis", "Black", "", "", 110],
        ]))
        assert errors == []
        assert rows[0]["skus"] == []
        assert rows[0]["sizes"] == []

    def test_row_number_reflects_excel_row(self):
        rows, _ = parse_excel(_xlsx([
            ["A", "C", "Blue", "S", "K", 100],
            ["A", "C", "Red", "S", "K", 100],
        ]))
        assert rows[0]["row_num"] == 2  # header is row 1
        assert rows[1]["row_num"] == 3
