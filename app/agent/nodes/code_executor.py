import asyncio
import io
import logging
import os
from pathlib import Path
import boto3
from botocore.config import Config
from dotenv import load_dotenv
import duckdb
import pandas as pd
from app.agent.state import AgentState
from app.services.storage import get_presigned_url
from e2b_code_interpreter import Sandbox

load_dotenv()

logger = logging.getLogger(__name__)

S3_BUCKET = os.getenv("S3_BUCKET_NAME") or os.getenv("AWS_S3_BUCKET") or "new-crashout"
AWS_REGION = os.getenv("AWS_REGION") or os.getenv("AWS_DEFAULT_REGION") or "eu-north-1"
AWS_ACCESS_KEY_ID = os.getenv("AWS_ACCESS_KEY_ID")
AWS_SECRET_ACCESS_KEY = os.getenv("AWS_SECRET_ACCESS_KEY")


def _load_dataframe(parquet_path: str) -> pd.DataFrame:
    path_obj = Path(parquet_path)
    if path_obj.exists() and path_obj.is_file():
        return pd.read_parquet(parquet_path)

    if parquet_path.startswith("http://") or parquet_path.startswith("https://") or parquet_path.startswith("s3://"):
        if S3_BUCKET in parquet_path:
            try:
                key_name = parquet_path.split("?")[0].split("/")[-1]
                s3 = boto3.client(
                    "s3",
                    region_name=AWS_REGION,
                    aws_access_key_id=AWS_ACCESS_KEY_ID,
                    aws_secret_access_key=AWS_SECRET_ACCESS_KEY,
                )
                buf = io.BytesIO()
                s3.download_fileobj(S3_BUCKET, key_name, buf)
                buf.seek(0)
                return pd.read_parquet(buf)
            except Exception as e:
                logger.warning(f"boto3 download failed for {parquet_path}: {e}")

        # Fallback with storage options if keys available
        if AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY:
            return pd.read_parquet(
                parquet_path,
                storage_options={"key": AWS_ACCESS_KEY_ID, "secret": AWS_SECRET_ACCESS_KEY}
            )
        return pd.read_parquet(parquet_path)

    return pd.read_parquet(parquet_path)

    return pd.read_parquet(parquet_path)


def _execute_sql(parquet_path: str, sql_query: str):
    con = duckdb.connect(":memory:")
    try:
        df = _load_dataframe(parquet_path)
        con.register("df", df)
        
        cleaned_query = sql_query.strip()
        if cleaned_query.startswith("```"):
            lines = cleaned_query.split("\n")
            if lines and lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].startswith("```"):
                lines = lines[:-1]
            cleaned_query = "\n".join(lines).strip()
            
        cleaned_query = cleaned_query.rstrip(";").strip()
        result_df = con.execute(cleaned_query).df()
        return result_df.to_dict(orient="records"), ""
    except Exception as e:
        logger.exception("DuckDB SQL execution error")
        return None, str(e)
    finally:
        con.close()


def _execute_python(parquet_path: str, generated_code: str):
    try:
        cleaned_code = generated_code.strip()
        if cleaned_code.startswith("```"):
            lines = cleaned_code.split("\n")
            if lines and lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].startswith("```"):
                lines = lines[:-1]
            cleaned_code = "\n".join(lines).strip()

        # If code reads parquet from S3, ensure presigned URL is injected
        if parquet_path and ("s3.amazonaws.com" in parquet_path or "s3." in parquet_path):
            presigned_url = get_presigned_url(parquet_path)
            cleaned_code = cleaned_code.replace(parquet_path, presigned_url)

        with Sandbox.create() as sandbox:
            execution = sandbox.run_code(cleaned_code, timeout=30)
            if execution.error:
                error_str = (
                    f"{execution.error.name}: {execution.error.value}"
                    if hasattr(execution.error, "name")
                    else str(execution.error)
                )
                return None, error_str

            output = "".join(execution.logs.stdout).strip() if isinstance(execution.logs.stdout, list) else (execution.logs.stdout or "").strip()
            if not output:
                return None, "The code ran successfully but produced no stdout output. Make sure to print the final result."
            return output, ""
    except Exception as e:
        logger.exception("E2B execution error")
        return None, f"Execution failed: {str(e)}"


async def run(state: AgentState) -> AgentState:
    if state.code_language == "sql":
        result, error = await asyncio.to_thread(
            _execute_sql, state.parquet_path, state.generated_code
        )
    else:
        result, error = await asyncio.to_thread(
            _execute_python, state.parquet_path, state.generated_code
        )

    if error:
        return state.model_copy(update={
            "execution_error": error,
            "retry_count": state.retry_count + 1,
            "execution_result": None,
        })

    return state.model_copy(update={
        "execution_result": result,
        "execution_error": "",
    })