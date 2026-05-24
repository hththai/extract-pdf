from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from services.pdf_extractor import PDFExtractor
from config import settings
import io
import tempfile
import shutil

app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["Content-Disposition"],
)
extractor = PDFExtractor()

@app.post("/extract-text")
async def extract_text(file: UploadFile = File(...)):
    if file.content_type != "application/pdf":
        raise HTTPException(status_code=400, detail="File must be a PDF")

    with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
        shutil.copyfileobj(file.file, tmp)
        tmp_path = tmp.name

    try:
        text = extractor.extract_text(tmp_path)
        return {"text": text}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/extract-csv")
async def extract_csv(file: UploadFile = File(...)):
    if file.content_type != "application/pdf":
        raise HTTPException(status_code=400, detail="File must be a PDF")

    try:
        pdf_buffer = io.BytesIO(await file.read())
        df = extractor.extract_transaction_table(pdf_buffer)
        df = extractor.convert_amount_balance_to_numbers(df)

        if not extractor.is_valid_result(df):
            raise HTTPException(status_code=400, detail="Validation failed")

        validation_status = extractor.is_valid_result(df)
        csv_name = f"true_validation_{len(df)}.csv" if validation_status else f"false_validation_{len(df)}.csv"

        csv_buffer = io.StringIO()
        df.to_csv(csv_buffer, index=False)
        csv_buffer.seek(0)

        return StreamingResponse(
            iter([csv_buffer.getvalue()]),
            media_type="text/csv",
            headers={"Content-Disposition": f"attachment; filename={csv_name}"},
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/status")
async def health_check():
    return {"status": "OK"}
