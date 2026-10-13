import os
import logging
from pathlib import Path
import boto3
from botocore.exceptions import ClientError
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

S3_BUCKET = os.getenv("S3_BUCKET_NAME") or os.getenv("AWS_S3_BUCKET") or "new-crashout"
AWS_REGION = os.getenv("AWS_REGION") or os.getenv("AWS_DEFAULT_REGION") or "eu-north-1"
AWS_ACCESS_KEY_ID = os.getenv("AWS_ACCESS_KEY_ID")
AWS_SECRET_ACCESS_KEY = os.getenv("AWS_SECRET_ACCESS_KEY")

s3_client = boto3.client(
    "s3",
    region_name=AWS_REGION,
    aws_access_key_id=AWS_ACCESS_KEY_ID,
    aws_secret_access_key=AWS_SECRET_ACCESS_KEY,
)


def get_presigned_url(parquet_path_or_key: str, expires_in: int = 604800) -> str:
    try:
        key = parquet_path_or_key.split("?")[0].split("/")[-1]
        return s3_client.generate_presigned_url(
            "get_object",
            Params={"Bucket": S3_BUCKET, "Key": key},
            ExpiresIn=expires_in,
        )
    except Exception as e:
        logger.warning(f"Failed to generate presigned URL: {e}")
        return parquet_path_or_key


def uploadtoS3(temp_file: Path | str) -> str:
    try:
        path = Path(temp_file)
        object_key = path.name
        
        s3_client.upload_file(str(path), S3_BUCKET, object_key)
        
        return get_presigned_url(object_key)
    except ClientError as e:
        logger.error(f"S3 upload error: {e}")
        raise RuntimeError(f"Failed to upload dataset to S3: {e}")



