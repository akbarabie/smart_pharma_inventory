"""
Script kecil untuk verifikasi koneksi ke Postgres GOLD/SILVER hosted (Neon/Supabase).
Jalankan ini sekali saja setelah setup .env, untuk memastikan connection string
sudah benar sebelum kita lanjut membangun extractor dan DAG.

Cara pakai:
    pip install psycopg2-binary python-dotenv
    python scripts/test_connection.py
"""

import os
import sys

from dotenv import load_dotenv
import psycopg2

# Baca file .env di root project
load_dotenv()

DATABASE_URL = os.getenv("GOLD_DATABASE_URL")


def main():
    if not DATABASE_URL:
        print("GOLD_DATABASE_URL belum diisi di file .env, cek dulu ya.")
        sys.exit(1)

    print("Mencoba konek ke Postgres hosted...")

    try:
        # connect_timeout dikasih 10 detik, karena Neon free tier
        # kadang butuh waktu "bangun" dulu (cold start) kalau lagi idle
        conn = psycopg2.connect(DATABASE_URL, connect_timeout=10)
        cursor = conn.cursor()

        cursor.execute("SELECT version();")
        versi_postgres = cursor.fetchone()[0]
        print("Berhasil konek.")
        print(f"Versi Postgres: {versi_postgres}")

        cursor.close()
        conn.close()

    except psycopg2.OperationalError as error:
        print("Gagal konek ke database. Cek lagi hal-hal berikut:")
        print("1. Connection string di .env sudah benar (bukan yang -pooler)")
        print("2. Tidak ada typo saat copy-paste password")
        print("3. Koneksi internet kamu tidak diblok firewall kampus/kantor")
        print(f"Detail error: {error}")
        sys.exit(1)


if __name__ == "__main__":
    main()
