import logging
import boto3
from botocore.exceptions import ClientError

def uploadtoS3(temp_file):
    s3_client = boto3.client("s3")
    try:
        # Convert path objects to strings for boto3
        file_path_str = str(temp_file)
        # Use only the filename for the S3 object key, not the full local path
        object_key = temp_file.name if hasattr(temp_file, 'name') else str(temp_file).split('\\')[-1]
        
        # boto3.client("s3").upload_file(Filename, Bucket, Key)
        s3_client.upload_file(file_path_str, "crashout-007", object_key)
        
        # Return the public S3 URL (assuming default aws format)
        return f"https://crashout-007.s3.us-east-2.amazonaws.com/{object_key}"
    except ClientError as e:
        logging.error(e)
        return False

