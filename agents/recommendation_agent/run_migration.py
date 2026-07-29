import os
from sqlalchemy import create_engine, text
from dotenv import load_dotenv

# Baca file .env di root project
load_dotenv()

# 1. URL Database Neon (dapatkan dari Dashboard Neon kamu)
# Jangan lupa pastikan sslmode=require terpasang
DATABASE_URL = os.getenv("GOLD_DATABASE_URL")

# 2. Buat engine SQLAlchemy
engine = create_engine(DATABASE_URL)

def run_sql_file(file_path):
    # Membaca isi file SQL
    with open(file_path, 'r', encoding='utf-8') as file:
        sql_script = file.read()

    # Membuka koneksi dan mengeksekusi script (engine.begin otomatis handle COMMIT)
    with engine.begin() as connection:
        # Bungkus query string dengan text()
        connection.execute(text(sql_script))
        print("✅ Berhasil mengeksekusi skema dan indeks ke database Neon!")

if __name__ == "__main__":
    # Ganti dengan nama file SQL kamu
    run_sql_file("create_table.sql")