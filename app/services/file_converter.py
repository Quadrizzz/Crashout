from __future__ import annotations

import asyncio
from io import BytesIO
from pathlib import Path
import json
import tempfile

import pandas as pd
from app.services.storage import uploadtoS3
from fastapi import HTTPException, UploadFile, status

MAX_UPLOAD_BYTES = 50 * 1024 * 1024  # 50 MB limit

SUPPORTED_EXTENSIONS = {
    ".csv",
    ".tsv",
    ".xls",
    ".xlsx",
    ".xlsm",
    ".json",
    ".jsonl",
    ".parquet",
}


def _read_json(file_bytes: bytes) -> pd.DataFrame:
    try:
        return pd.read_json(BytesIO(file_bytes))
    except ValueError:
        raw = json.loads(file_bytes.decode("utf-8"))
        if isinstance(raw, list):
            return pd.json_normalize(raw)
        if isinstance(raw, dict):
            return pd.json_normalize(raw)
        return pd.DataFrame({"value": [raw]})


def _read_dataframe(file_bytes: bytes, extension: str) -> pd.DataFrame:
    if extension == ".csv":
        return pd.read_csv(BytesIO(file_bytes))
    if extension == ".tsv":
        return pd.read_csv(BytesIO(file_bytes), sep="\t")
    if extension in {".xls", ".xlsx", ".xlsm"}:
        return pd.read_excel(BytesIO(file_bytes))
    if extension == ".json":
        return _read_json(file_bytes)
    if extension == ".jsonl":
        return pd.read_json(BytesIO(file_bytes), lines=True)
    if extension == ".parquet":
        return pd.read_parquet(BytesIO(file_bytes))

    raise HTTPException(status_code=400, detail=f"Unsupported file type: {extension}")


def _process_and_save_parquet(file_bytes: bytes, extension: str, session_id: str) -> Path:
    df = _read_dataframe(file_bytes, extension)
    if df.empty:
        raise HTTPException(status_code=400, detail="Uploaded file has no rows.")

    parquet_path = Path(tempfile.gettempdir()) / f"{session_id}.parquet"
    df.to_parquet(parquet_path, engine="pyarrow", index=False)
    return parquet_path


async def convert_to_parquet(file: UploadFile, session_id: str) -> str:
    filename = file.filename or ""
    extension = Path(filename).suffix.lower()

    if extension not in SUPPORTED_EXTENSIONS:
        supported = ", ".join(sorted(SUPPORTED_EXTENSIONS))
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type '{extension or '(none)'}'. Supported: {supported}",
        )

    file_bytes = await file.read()
    if not file_bytes:
        raise HTTPException(status_code=400, detail="Uploaded file is empty.")

    if len(file_bytes) > MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"File too large. Maximum allowed size is {MAX_UPLOAD_BYTES // (1024 * 1024)}MB.",
        )

    parquet_path: Path | None = None
    try:
        parquet_path = await asyncio.to_thread(
            _process_and_save_parquet, file_bytes, extension, session_id
        )
        s3_url = await asyncio.to_thread(uploadtoS3, parquet_path)
        return s3_url
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=400,
            detail=f"Failed to process '{filename}': {exc}",
        ) from exc
    finally:
        if parquet_path and parquet_path.exists():
            try:
                parquet_path.unlink()
            except Exception:
                pass

