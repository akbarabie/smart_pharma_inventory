"""
Modul kecil untuk koneksi ke MinIO (bronze layer object storage).
Dipakai bersama oleh semua extractor supaya tidak duplikasi kode koneksi.
"""

import os

import boto3
from botocore.client import Config
from dotenv import load_dotenv

# Baca file .env kalau dijalankan manual dari laptop (di luar docker).
# Di dalam container Airflow, ini tidak akan menemukan file .env (memang
# tidak di-mount), tapi tidak masalah, load_dotenv() diam saja kalau file
# tidak ketemu, dan env variable sudah di-inject langsung oleh docker-compose.
load_dotenv()


def get_minio_client():
    """
    Membuat client boto3 yang diarahkan ke MinIO, bukan AWS S3 asli.

    Endpoint beda tergantung dari mana script ini dipanggil:
    - Dari dalam container Airflow: docker-compose sudah set MINIO_ENDPOINT=minio:9000
    - Dari laptop langsung (testing manual sebelum masuk DAG): pakai localhost:9000,
      karena port MinIO sudah di-expose ke host lewat docker-compose.
    """
    endpoint = os.getenv("MINIO_ENDPOINT", "localhost:9000")
    access_key = os.getenv("MINIO_ACCESS_KEY") or os.getenv("MINIO_ROOT_USER", "minioadmin")
    secret_key = os.getenv("MINIO_SECRET_KEY") or os.getenv("MINIO_ROOT_PASSWORD", "minioadmin123")

    return boto3.client(
        "s3",
        endpoint_url=f"http://{endpoint}",
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
        config=Config(signature_version="s3v4"),
        region_name="us-east-1",  # dummy, MinIO tidak peduli region tapi boto3 wajib diisi
    )


def upload_file_to_bronze(local_path, bucket_key, bucket_name="bronze"):
    """
    Upload satu file lokal ke bucket bronze di MinIO.

    local_path  : path file di disk lokal, misal "data/raw/fornas/gabungan.csv"
    bucket_key  : nama key/path di dalam bucket, misal "fornas/fornas_raw_gabungan.csv"

    Sengaja dibungkus try/except di level pemanggil (bukan di sini), supaya
    kegagalan upload tidak bikin keseluruhan script mati tanpa pesan jelas.
    """
    client = get_minio_client()
    client.upload_file(local_path, bucket_name, bucket_key)
    print(f"Upload berhasil: {local_path} -> s3://{bucket_name}/{bucket_key}")


def download_file_from_bronze(bucket_key, local_path, bucket_name="bronze"):
    """
    Download satu file dari bucket bronze di MinIO ke disk lokal (biasanya
    folder sementara), dipakai tahap Silver supaya sumber datanya benar-benar
    dari bronze/MinIO, bukan dari file mentah di laptop yang bisa saja beda
    isinya atau tidak ada sama sekali.
    """
    os.makedirs(os.path.dirname(local_path) or ".", exist_ok=True)
    client = get_minio_client()
    client.download_file(bucket_name, bucket_key, local_path)
    print(f"Download berhasil: s3://{bucket_name}/{bucket_key} -> {local_path}")