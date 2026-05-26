import asyncio
import io
import os
import tempfile
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated

import pandas as pd
from fastapi import BackgroundTasks, FastAPI, APIRouter, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

from config import settings
from middleware.access_log import AccessLogMiddleware
from services.job_store import Job, JobStore
from services.pdf_extractor import PDFExtractor
from services.transaction_classifier import TransactionClassifierService


job_store = JobStore()
extractor = PDFExtractor()
classifier = TransactionClassifierService()


@asynccontextmanager
async def lifespan(_app: FastAPI):
    async def _cleanup_loop():
        while True:
            await asyncio.sleep(300)
            job_store.cleanup()

    task = asyncio.create_task(_cleanup_loop())
    yield
    task.cancel()


app = FastAPI(lifespan=lifespan)
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

router = APIRouter(prefix="/api")

PDF_MAGIC = b"%PDF"
CSV_MEDIA_TYPE = "text/csv"
CSV_CONTENT_TYPES = {CSV_MEDIA_TYPE, "application/csv", "text/plain", "application/octet-stream"}


def _safe_stem(filename: str | None) -> str:
    stem = Path(filename).stem if filename else "transactions"
    return "".join(c for c in stem if c.isalnum() or c in "_-") or "transactions"


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


async def _run_classification(job: Job, df: pd.DataFrame) -> None:
    job.status = "processing"
    categories: list[str] = []
    try:
        async for _row_values, category in classifier.classify_stream(df):
            categories.append(category)
            job.progress += 1

        result = df.copy()
        result["Category"] = categories
        job.result = result
        job.status = "done"
    except Exception as e:
        job.status = "error"
        job.error = str(e)


# ---------------------------------------------------------------------------
# PDF endpoints
# ---------------------------------------------------------------------------

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

        if not extractor.is_valid_result(df):
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


# ---------------------------------------------------------------------------
# CSV classification — background job
# ---------------------------------------------------------------------------

@router.post(
    "/classify-csv",
    status_code=202,
    responses={
        400: {"description": "Not a CSV or missing required column"},
        413: {"description": "File too large"},
    },
)
async def classify_csv_submit(
    background_tasks: BackgroundTasks,
    file: Annotated[UploadFile, File()],
):
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
    job = job_store.create(filename=output_name, total=len(df))
    background_tasks.add_task(_run_classification, job, df)

    return {"job_id": job.id, "total": job.total}


@router.get(
    "/classify-csv/{job_id}",
    responses={404: {"description": "Job not found"}},
)
async def classify_csv_status(job_id: str):
    job = job_store.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")

    return {
        "job_id": job.id,
        "status": job.status,
        "progress": job.progress,
        "total": job.total,
        "error": job.error,
    }


@router.get(
    "/classify-csv/{job_id}/download",
    responses={
        400: {"description": "Job not ready"},
        404: {"description": "Job not found"},
    },
)
async def classify_csv_download(job_id: str):
    job = job_store.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    if job.status != "done":
        raise HTTPException(status_code=400, detail=f"Job is not ready (status: {job.status})")

    buf = io.StringIO()
    job.result.to_csv(buf, index=False)
    buf.seek(0)

    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type=CSV_MEDIA_TYPE,
        headers={"Content-Disposition": f"attachment; filename={job.filename}"},
    )


@router.get("/status")
async def health_check():
    return {"status": "OK"}


app.include_router(router)
