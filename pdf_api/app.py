from typing import Annotated
from fastapi import FastAPI, APIRouter, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from services.pdf_extractor import PDFExtractor
from middleware.access_log import AccessLogMiddleware
from config import settings
import io
import os
import tempfile

app = FastAPI()
app.add_middleware(
    AccessLogMiddleware,
    log_dir=settings.LOG_DIR,
    retention_days=settings.LOG_RETENTION_DAYS,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["Content-Disposition"],
)
extractor = PDFExtractor()
router = APIRouter(prefix="/api")

PDF_MAGIC = b"%PDF"

async def read_validated_pdf(file: UploadFile) -> bytes:
    data = await file.read()
    if len(data) > settings.MAX_PDF_BYTES:
        raise HTTPException(status_code=413, detail=f"File exceeds {settings.MAX_PDF_BYTES} bytes")
    if not data.startswith(PDF_MAGIC):
        raise HTTPException(status_code=400, detail="File must be a PDF")
    return data

@router.post(
    "/extract-text",
    responses={
        400: {"description": "Not a PDF"},
        413: {"description": "File too large"},
        500: {"description": "Extraction error"},
    },
)
async def extract_text(file: Annotated[UploadFile, File()]):
    data = await read_validated_pdf(file)
    fd, tmp_path = tempfile.mkstemp(suffix=".pdf")
    try:
        os.write(fd, data)
    finally:
        os.close(fd)
    try:
        text = extractor.extract_text(tmp_path)
        return {"text": text}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        os.unlink(tmp_path)

@router.post(
    "/extract-csv",
    responses={
        400: {"description": "Not a PDF or validation failed"},
        413: {"description": "File too large"},
        500: {"description": "Extraction error"},
    },
)
async def extract_csv(file: Annotated[UploadFile, File()]):
    data = await read_validated_pdf(file)
    try:
        pdf_buffer = io.BytesIO(data)
        df = extractor.extract_transaction_table(pdf_buffer)
        df = extractor.convert_amount_balance_to_numbers(df)

        validation_status = extractor.is_valid_result(df)
        if not validation_status:
            raise HTTPException(status_code=400, detail="Validation failed")

        csv_name = f"true_validation_{len(df)}.csv"
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

@router.get("/status")
async def health_check():
    return {"status": "OK"}

app.include_router(router)
