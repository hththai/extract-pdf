import pytest
from services.pdf_extractor import PDFExtractor
from reportlab.pdfgen import canvas
from pathlib import Path

def create_test_pdf(path: str, text: str):
    from reportlab.pdfgen import canvas
    c = canvas.Canvas(path)
    c.drawString(100, 750, text)
    c.save()

def test_extract_text(tmp_path):
    # Arrange
    pdf_path = tmp_path / "sample.pdf"
    expected_text = "Hello PDF"
    create_test_pdf(str(pdf_path), expected_text)

    extractor = PDFExtractor()

    # Act
    result = extractor.extract_text(str(pdf_path))

    # Assert
    assert expected_text in result

def test_extract_text_from_file():
    # Arrange
    pdf_path = Path(__file__).parent / "temp"/"sample.pdf"

    extractor = PDFExtractor()

    # Act
    result = extractor.extract_text(str(pdf_path))

    # Print the extracted text
    print("\n--- Extracted Text ---")
    print(result)
    print("----------------------")

def test_extract_transaction():
    # Arrange
    pdf_path = Path(__file__).parent / "temp"/"sample.pdf"

    extractor = PDFExtractor()

    # Act
    result = extractor.extract_transaction_table(str(pdf_path))

    result = extractor.convert_amount_balance_to_numbers(result)

    # Print the extracted text
    print("\n--- Extracted Text ---")
    print(result)
    print("----------------------")
    


    # Convert the result to a DataFrame and save it as a CSV file
    import pandas as pd
    df = pd.DataFrame(result)
    csv_path = Path(__file__).parent / "temp"/"result"
    if not csv_path.exists():
        csv_path.mkdir(parents=True, exist_ok=True)
    csv_path /= "extracted_transactions.csv"
    df.to_csv(csv_path, index=False)

    # Print the path of the saved CSV file
    print("\n--- Saved CSV File ---")
    print(str(csv_path))
    print("----------------------")
