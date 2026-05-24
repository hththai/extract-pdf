import pdfplumber
from pathlib import Path
import pandas as pd
from datetime import datetime
from dataclasses import dataclass


class PDFExtractor:

    @dataclass(frozen=True)
    class _ColumnBounds:
        date_max: float = 120
        details_max: float = 350
        amount_max: float = 450

    COLUMN_BOUNDS = _ColumnBounds()

    def is_valid_date(self, date_str: str) -> bool:
        if not date_str or not date_str[0].isdigit():
            return False

        for fmt in ("%d %B %Y", "%d %b %Y", "%d/%m/%Y", "%d-%m-%Y", "%d/%m/%y"):
            try:
                datetime.strptime(date_str, fmt)
                return True
            except ValueError:
                continue
        return False

    def extract_text(self, file_path: str) -> str:
        path = Path(file_path)

        if not path.exists():
            raise FileNotFoundError(f"File not found: {file_path}")

        if path.suffix.lower() != ".pdf":
            raise ValueError("Only PDF files are supported")

        text_chunks = []

        with pdfplumber.open(path) as pdf:
            for page in pdf.pages:
                text = page.extract_text() or ""
                text_chunks.append(text)

        return "\n".join(text_chunks).strip()

    def extract_transaction_table(self, pdf_source) -> pd.DataFrame:
        results = []
        with pdfplumber.open(pdf_source) as pdf:
            for page in pdf.pages:
                self._extract_page_transactions(page, results)
        return pd.DataFrame(results)

    def _extract_page_transactions(self, page, results: list) -> None:
        words = page.extract_words(use_text_flow=True)
        if not words:
            return

        df = pd.DataFrame(words)
        if not {"text", "x0", "top"}.issubset(df.columns):
            return

        df["row"] = df["top"].round(1)
        table_started = False

        for _, group in df.groupby("row"):
            row_data = self._parse_row(group)

            if not table_started:
                table_started = self._is_header_row(row_data["line_text"])
                continue

            if self._is_footer_row(row_data["line_text"]):
                break

            if self._is_continuation_row(row_data, results):
                results[-1]["Transaction details"] += " " + row_data["details"]
                continue

            if self._is_valid_transaction(row_data):
                results.append(self._make_transaction(row_data))

    def _make_transaction(self, row_data: dict) -> dict:
        return {
            "Date": row_data["date"],
            "Transaction details": row_data["details"],
            "Amount": row_data["amount"],
            "Balance": row_data["balance"],
        }

    def _parse_row(self, group):
        row_sorted = group.sort_values("x0")
        texts = list(row_sorted["text"])
        xs = list(row_sorted["x0"])

        date, details, amount, balance = "", "", "", ""

        for t, x in zip(texts, xs):
            if x < self.COLUMN_BOUNDS.date_max:
                date += t + " "
            elif x < self.COLUMN_BOUNDS.details_max:
                details += t + " "
            elif x < self.COLUMN_BOUNDS.amount_max:
                amount += t + " "
            else:
                balance += t + " "

        return {
            "date": date.strip(),
            "details": details.strip(),
            "amount": amount.strip(),
            "balance": balance.strip(),
            "line_text": " ".join(texts)
        }


    def _is_header_row(self, line_text: str) -> bool:
        return "Date" in line_text and "Transaction" in line_text


    def _is_footer_row(self, line_text: str) -> bool:
        return "Total" in line_text


    def _is_continuation_row(self, row, results) -> bool:
        return (
            row["date"] == "" and
            row["amount"] == "" and
            row["balance"] == "" and
            row["details"] != "" and
            len(results) > 0
        )


    def _is_valid_transaction(self, row) -> bool:
        return self.is_valid_date(row["date"]) and (row["amount"] or row["balance"])

    
    def convert_amount_balance_to_numbers(self, df: pd.DataFrame) -> pd.DataFrame:
        def extract_number(value):
            if not isinstance(value, str) or value.strip() == "":
                return None

            v = value.strip()

            # Remove currency symbols and commas
            v = v.replace("$", "").replace(",", "")

            # Handle CR/DR (credit/debit)
            if v.endswith("CR"):
                v = v[:-2].strip()
            if v.endswith("DR"):
                v = "-" + v[:-2].strip()

            # Normalize negative formats
            # -$123.45 → -123.45
            # $-123.45 → -123.45
            v = v.replace(" ", "")
            if v.startswith("-"):
                sign = -1
                v = v[1:]
            else:
                sign = 1

            try:
                return sign * float(v)
            except ValueError:
                return None

        df["Amount_num"] = df["Amount"].apply(extract_number)
        df["Balance_num"] = df["Balance"].apply(extract_number)

        return df
    
    # Validate result if it total balance match.
    def is_valid_result(
        self,
        df: pd.DataFrame,
        amount_col: str = "Amount_num",
        balance_col: str = "Balance_num",
    ) -> bool:
        if df.empty:
            return False

        # Closing balance (last row)
        last_balance = df.iloc[-1][balance_col]

        # Sum of all transaction amounts
        sum_amount = df[amount_col].sum()

        # Opening balance = first balance BEFORE first transaction
        opening_balance = df.iloc[0][balance_col] - df.iloc[0][amount_col]
    
        # Expected closing balance
        expected_balance = opening_balance + sum_amount

        # debug
        # print(f"LAST BALANCE: {last_balance}")
        # print(f"EXPECTED BALANCE: {expected_balance}")

        # Compare with tolerance for floating point
        return abs(expected_balance - last_balance) < 0.01

    def save_validated_csv(self, df: pd.DataFrame, file_path: str) -> None:
        validation_status = self.is_valid_result(df)
        if validation_status:
            csv_name = f"true_validation_{len(df)}.csv"
        else:
            csv_name = f"false_validation_{len(df)}.csv"

        output_file = Path(file_path)/csv_name
        df.to_csv(output_file, index=False)
