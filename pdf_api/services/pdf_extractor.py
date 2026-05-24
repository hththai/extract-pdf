import pdfplumber
from pathlib import Path
import pandas as pd
from datetime import datetime

class PDFExtractor:

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

    def extract_transaction_table(self, pdf_path: str) -> pd.DataFrame:
        results = []

        with pdfplumber.open(pdf_path) as pdf:
            for page in pdf.pages:

                words = page.extract_words(use_text_flow=True)

                if not words:
                    continue

                df = pd.DataFrame(words)

                if not {"text", "x0", "top"}.issubset(df.columns):
                    continue

                # group rows
                df["row"] = df["top"].round(1)
                rows = df.groupby("row")

                table_started = False

                for _, group in rows:
                    row_sorted = group.sort_values("x0")

                    texts = list(row_sorted["text"])
                    xs = list(row_sorted["x0"])

                    if not texts:
                        continue

                    line_text = " ".join(texts)

                    # detect header
                    if not table_started:
                        if "Date" in line_text and "Transaction" in line_text:
                            table_started = True
                        continue

                    # stop when reaching footer/summary
                    if "Total" in line_text:
                        break

                    # initialize row
                    date = ""
                    details = ""
                    amount = ""
                    balance = ""

                    # column boundaries (tune if needed)
                    for t, x in zip(texts, xs):
                        if x < 120:
                            date += t + " "
                        elif x < 300:
                            details += t + " "
                        elif x < 450:
                            amount += t + " "
                        else:
                            balance += t + " "

                    # clean
                    date = date.strip()
                    details = details.strip()
                    amount = amount.strip()
                    balance = balance.strip()

                    # Detect continuation line (multi-line description)
                    is_continuation = (
                        date == "" and
                        amount == "" and
                        balance == "" and
                        details != ""
                    )

                    if is_continuation and results:
                        results[-1]["Transaction details"] += " " + details
                        continue

                    if self.is_valid_date(date) and (amount or balance):
                        results.append({
                            "Date": date,
                            "Transaction details": details,
                            "Amount": amount,
                            "Balance": balance
                        })

        return pd.DataFrame(results)
    
    
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

        # Compare with tolerance for floating point
        return abs(expected_balance - last_balance) < 0.01

