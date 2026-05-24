from fastapi import FastAPI, UploadFile, File, HTTPException
from services.pdf_extractor import PDFExtractor
import tempfile
import shutil

app = FastAPI()
extractor = PDFExtractor()

@app.post("/extract-text")
async def extract_text(file: UploadFile = File(...)):
    if file.content_type != "application/pdf":
        raise HTTPException(status_code=400, detail="File must be a PDF")

    # Save uploaded file to a temporary location
    with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
        shutil.copyfileobj(file.file, tmp)
        tmp_path = tmp.name

    try:
        text = extractor.extract_text(tmp_path)
        return {"text": text}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

## health check api
@app.get("/status")
async def health_check():
    return {"status": "OK"}
