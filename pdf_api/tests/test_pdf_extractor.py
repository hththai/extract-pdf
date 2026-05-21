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

    # Print the extracted text
    print("\n--- Extracted Text ---")
    print(result)
    print("----------------------")
