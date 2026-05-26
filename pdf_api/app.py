import io
import json
import math
import os
import tempfile
from pathlib import Path
from typing import Annotated
from fastapi import FastAPI, APIRouter, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from services.pdf_extractor import PDFExtractor
from services.transaction_classifier import TransactionClassifierService
from middleware.access_log import AccessLogMiddleware
from config import settings
import pandas as pd

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
classifier = TransactionClassifierService()
router = APIRouter(prefix="/api")

PDF_MAGIC = b"%PDF"
CSV_MEDIA_TYPE = "text/csv"
CSV_CONTENT_TYPES = {CSV_MEDIA_TYPE, "application/csv", "text/plain", "application/octet-stream"}


def _safe_stem(filename: str | None) -> str:
    stem = Path(filename).stem if filename else "transactions"
    return "".join(c for c in stem if c.isalnum() or c in "_-") or "transactions"


def _json_safe(v):
    """Convert numpy scalars and NaN to JSON-serialisable Python types."""
    if hasattr(v, "item"):
        v = v.item()
    try:
        if math.isnan(v):
            return None
    except TypeError:
        pass
    return v


def _sse(data: dict) -> str:
    return f"data: {json.dumps(data)}\n\n"


async def read_validated_pdf(file: UploadFile) -> bytes:
    data = await file.read()
    if len(data) > settings.MAX_PDF_BYTES:
        raise HTTPException(status_code=413, detail=f"File exceeds {settings.MAX_PDF_BYTES} bytes")
    if not data.startswith(PDF_MAGIC):
        raise HTTPException(status_code=400, detail="File must be a PDF")
    return data


async def read_validated_csv(file: UploadFile) -> bytes:
    if file.content_type not in CSV_CONTENT_TYPES:
        raise HTTPException(status_code=400, detail="File must be a CSV")
    data = await file.read()
    if len(data) > settings.MAX_CSV_BYTES:
        raise HTTPException(status_code=413, detail=f"File exceeds {settings.MAX_CSV_BYTES} bytes")
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
            media_type=CSV_MEDIA_TYPE,
            headers={"Content-Disposition": f"attachment; filename={csv_name}"},
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post(
    "/classify-csv",
    responses={
        400: {"description": "Not a CSV or missing required column"},
        413: {"description": "File too large"},
    },
)
async def classify_csv(file: Annotated[UploadFile, File()]):
    data = await read_validated_csv(file)

    try:
        df = pd.read_csv(io.BytesIO(data))
    except Exception:
        raise HTTPException(status_code=400, detail="Could not parse CSV file")

    if "Transaction details" not in df.columns:
        raise HTTPException(
            status_code=400,
            detail="CSV must contain a 'Transaction details' column",
        )

    output_name = f"{_safe_stem(file.filename)}_classified.csv"
    columns = list(df.columns) + ["Category"]

    async def generate():
        try:
            yield _sse({"type": "start", "total": len(df), "columns": columns})
            async for row_values, category in classifier.classify_stream(df):
                yield _sse({
                    "type": "row",
                    "values": [_json_safe(v) for v in row_values],
                    "category": category,
                })
            yield _sse({"type": "done", "filename": output_name})
        except Exception as e:
            yield _sse({"type": "error", "message": str(e)})

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/status")
async def health_check():
    return {"status": "OK"}


app.include_router(router)
