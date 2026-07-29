"""
Transform Bronze -> Silver.

Membaca data mentah dari bronze layer (MinIO), membersihkan, dan menyimpan
ke schema "silver" di Postgres hosted (Neon).

Aturan pembersihan:
    Fornas:
        - Hapus duplikat (nama_obat, nama_obat_internasional)
        - Tambah flag_vital = True (semua obat di Fornas itu vital by definition,
          itulah kenapa dia masuk daftar ini)

    Stock movement:
        - Hapus baris duplikat persis
        - Parse kolom tanggal yang formatnya campur (YYYY-MM-DD dan DD/MM/YYYY)
        - Baris dengan batch_id kosong ATAU jumlah_masuk/jumlah_keluar negatif
          di-KARANTINA ke tabel silver.rejected_stock_movement (bukan dihapus
          diam-diam), lengkap dengan alasan penolakannya, supaya ada jejak audit

CATATAN PENTING: obat_id (surrogate key) SENGAJA BELUM dibuat di sini.
Itu keputusan dimensional modeling, tempatnya di tahap Gold, bukan Silver.
Silver cuma bersihkan dan standarisasi, natural key (nama_obat) tetap dipakai.

Idempotent: tiap run melakukan TRUNCATE + INSERT ulang, aman dijalankan
berkali-kali tanpa duplikasi data.

Cara pakai:
    python transform/transform_to_silver.py
"""

import os
import sys

import pandas as pd
import psycopg2
from dotenv import load_dotenv
from psycopg2.extras import execute_values

sys.path.append(os.path.join(os.path.dirname(__file__), "..", "extractors"))
from minio_client import download_file_from_bronze  # noqa: E402

load_dotenv()

TMP_DIR = "/tmp/silver_downloads"


def get_pg_connection():
    database_url = os.getenv("GOLD_DATABASE_URL")
    if not database_url:
        raise RuntimeError("GOLD_DATABASE_URL belum diset di .env")
    return psycopg2.connect(database_url)


def buat_schema_dan_tabel(conn):
    with conn.cursor() as cur:
        cur.execute("""
            CREATE SCHEMA IF NOT EXISTS silver;

            CREATE TABLE IF NOT EXISTS silver.stg_obat (
                nama_obat TEXT PRIMARY KEY,
                nama_obat_internasional TEXT,
                flag_vital BOOLEAN,
                sumber_file TEXT,
                diekstrak_pada TIMESTAMPTZ,
                dimuat_pada TIMESTAMPTZ DEFAULT now()
            );

            CREATE TABLE IF NOT EXISTS silver.stg_stock_movement (
                tanggal DATE,
                obat_kode TEXT,
                obat_nama TEXT,
                gudang_kode TEXT,
                gudang_nama TEXT,
                batch_id TEXT,
                tanggal_kadaluwarsa DATE,
                jumlah_masuk INTEGER,
                jumlah_keluar INTEGER,
                dimuat_pada TIMESTAMPTZ DEFAULT now()
            );

            CREATE TABLE IF NOT EXISTS silver.rejected_stock_movement (
                tanggal TEXT,
                obat_kode TEXT,
                obat_nama TEXT,
                gudang_kode TEXT,
                gudang_nama TEXT,
                batch_id TEXT,
                tanggal_kadaluwarsa TEXT,
                jumlah_masuk NUMERIC,
                jumlah_keluar NUMERIC,
                alasan_ditolak TEXT,
                dimuat_pada TIMESTAMPTZ DEFAULT now()
            );
        """)
    conn.commit()
    print("Schema dan tabel silver siap.")


def transform_fornas(conn):
    local_path = f"{TMP_DIR}/daftar_obat.csv"
    download_file_from_bronze("fornas/daftar_obat.csv", local_path)
    df = pd.read_csv(local_path)

    sebelum = len(df)
    df = df.drop_duplicates(subset=["nama_obat", "nama_obat_internasional"], keep="first").copy()
    print(f"Fornas: {sebelum} baris mentah -> {len(df)} baris setelah dedup "
          f"({sebelum - len(df)} duplikat dibuang)")

    df["nama_obat"] = df["nama_obat"].str.strip()
    df["nama_obat_internasional"] = df["nama_obat_internasional"].str.strip()
    df["flag_vital"] = True

    kolom = ["nama_obat", "nama_obat_internasional", "flag_vital", "sumber_file", "diekstrak_pada"]
    with conn.cursor() as cur:
        cur.execute("TRUNCATE TABLE silver.stg_obat")
        execute_values(
            cur,
            f"INSERT INTO silver.stg_obat ({', '.join(kolom)}) VALUES %s",
            df[kolom].values.tolist(),
        )
    conn.commit()
    print(f"silver.stg_obat: {len(df)} baris dimuat")


def parse_tanggal_fleksibel(kolom):
    """Parse kolom tanggal yang formatnya campur ISO (YYYY-MM-DD) dan DD/MM/YYYY."""
    hasil_iso = pd.to_datetime(kolom, format="%Y-%m-%d", errors="coerce")
    hasil_slash = pd.to_datetime(kolom, format="%d/%m/%Y", errors="coerce")
    return hasil_iso.fillna(hasil_slash)


def transform_stock_movement(conn):
    local_path = f"{TMP_DIR}/stock_movement_synthetic.csv"
    download_file_from_bronze("stock_movement/stock_movement_synthetic.csv", local_path)
    df = pd.read_csv(local_path)

    sebelum = len(df)
    df = df.drop_duplicates(keep="first").reset_index(drop=True)
    print(f"Stock movement: {sebelum} baris mentah -> {len(df)} baris setelah dedup "
          f"({sebelum - len(df)} duplikat dibuang)")

    # Simpan versi string asli SEBELUM di-parse. Kalau ada baris yang ditolak,
    # kita tampilkan tanggal aslinya di tabel rejected, bukan hasil parse yang
    # sudah jadi NaT/kosong, supaya gampang di-debug manusia.
    df["tanggal_asli"] = df["tanggal"]
    df["tanggal_kadaluwarsa_asli"] = df["tanggal_kadaluwarsa"]
    df["tanggal"] = parse_tanggal_fleksibel(df["tanggal"])
    df["tanggal_kadaluwarsa"] = parse_tanggal_fleksibel(df["tanggal_kadaluwarsa"])

    kondisi_valid = (
        df["batch_id"].notna()
        & (df["jumlah_masuk"] >= 0)
        & (df["jumlah_keluar"] >= 0)
        & df["tanggal"].notna()
        & df["tanggal_kadaluwarsa"].notna()
    )

    df_valid = df[kondisi_valid].copy()
    df_ditolak = df[~kondisi_valid].copy()

    def alasan(row):
        sebab = []
        if pd.isna(row["batch_id"]):
            sebab.append("batch_id kosong")
        if row["jumlah_masuk"] < 0:
            sebab.append("jumlah_masuk negatif")
        if row["jumlah_keluar"] < 0:
            sebab.append("jumlah_keluar negatif")
        if pd.isna(row["tanggal"]):
            sebab.append("tanggal tidak bisa di-parse")
        if pd.isna(row["tanggal_kadaluwarsa"]):
            sebab.append("tanggal_kadaluwarsa tidak bisa di-parse")
        return ", ".join(sebab)

    if len(df_ditolak) > 0:
        df_ditolak["alasan_ditolak"] = df_ditolak.apply(alasan, axis=1)
        # Tampilkan tanggal ASLI (string) di tabel rejected, bukan hasil parse
        df_ditolak["tanggal"] = df_ditolak["tanggal_asli"]
        df_ditolak["tanggal_kadaluwarsa"] = df_ditolak["tanggal_kadaluwarsa_asli"]

    print(f"Stock movement: {len(df_valid)} baris valid, {len(df_ditolak)} baris di-karantina")

    kolom_valid = ["tanggal", "obat_kode", "obat_nama", "gudang_kode", "gudang_nama",
                   "batch_id", "tanggal_kadaluwarsa", "jumlah_masuk", "jumlah_keluar"]
    kolom_ditolak = kolom_valid + ["alasan_ditolak"]

    with conn.cursor() as cur:
        cur.execute("TRUNCATE TABLE silver.stg_stock_movement")
        execute_values(
            cur,
            f"INSERT INTO silver.stg_stock_movement ({', '.join(kolom_valid)}) VALUES %s",
            df_valid[kolom_valid].values.tolist(),
        )

        cur.execute("TRUNCATE TABLE silver.rejected_stock_movement")
        if len(df_ditolak) > 0:
            execute_values(
                cur,
                f"INSERT INTO silver.rejected_stock_movement ({', '.join(kolom_ditolak)}) VALUES %s",
                df_ditolak[kolom_valid + ["alasan_ditolak"]].values.tolist(),
            )
    conn.commit()
    print(f"silver.stg_stock_movement: {len(df_valid)} baris dimuat")
    print(f"silver.rejected_stock_movement: {len(df_ditolak)} baris dimuat")


def main():
    os.makedirs(TMP_DIR, exist_ok=True)
    conn = get_pg_connection()
    try:
        buat_schema_dan_tabel(conn)
        transform_fornas(conn)
        transform_stock_movement(conn)
    finally:
        conn.close()
    print("\nTransform ke Silver selesai.")


if __name__ == "__main__":
    main()
