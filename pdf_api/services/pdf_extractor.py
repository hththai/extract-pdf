import pdfplumber
from pathlib import Path

class PDFExtractor:
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

                # ✅ group rows
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

                    # ✅ detect header
                    if not table_started:
                        if "Date" in line_text and "Transaction" in line_text:
                            table_started = True
                        continue

                    # ✅ stop when reaching footer/summary
                    if "Total" in line_text:
                        break

                    # ✅ initialize row
                    date = ""
                    details = ""
                    amount = ""
                    balance = ""

                    # ✅ column boundaries (tune if needed)
                    for t, x in zip(texts, xs):
                        if x < 120:
                            date += t + " "
                        elif x < 300:
                            details += t + " "
                        elif x < 450:
                            amount += t + " "
                        else:
                            balance += t + " "

                    # ✅ clean
                    date = date.strip()
                    details = details.strip()
                    amount = amount.strip()
                    balance = balance.strip()

                    # ✅ simple validation
                    if date and (amount or balance):
                        results.append({
                            "Date": date,
                            "Transaction details": details,
                            "Amount": amount,
                            "Balance": balance
                        })

        return pd.DataFrame(results)
