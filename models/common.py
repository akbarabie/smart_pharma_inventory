"""
Modul bersama untuk script training model Data Scientist.

Isinya cuma dua hal yang dipakai berulang di kedua script training
(train_expiry_risk.py dan train_demand_forecast.py), supaya logikanya
cuma didefinisikan sekali di satu tempat:

1. Koneksi ke database gold layer (Neon Postgres)
2. Query data pergerakan stok mentah + agregasi ke level demand harian
   dengan kalender penuh (hari tanpa transaksi diisi nol, bukan hilang)

Kalau logika agregasi ini berubah di kemudian hari, cukup diedit di sini,
tidak perlu ubah dua file terpisah.
"""

import os

import pandas as pd
from dotenv import load_dotenv
from sqlalchemy import create_engine


def buat_koneksi_database():
    """Baca connection string dari .env dan buat engine SQLAlchemy.

    Wajib dijalankan dari root repo (python models/nama_script.py) supaya
    python-dotenv bisa menemukan file .env di direktori kerja saat ini.
    """
    load_dotenv()
    db_url = os.getenv("GOLD_DATABASE_URL")
    if not db_url:
        raise RuntimeError(
            "GOLD_DATABASE_URL tidak ditemukan di .env, "
            "cek lagi apakah file .env ada di root repo dan sudah terisi"
        )
    return create_engine(db_url)


def ambil_data_pergerakan(engine):
    """Ambil seluruh data pergerakan stok dari gold layer, sudah di-join
    dengan dimensi obat, gudang, dan waktu.

    Query ini sengaja mengambil semua kolom yang dibutuhkan kedua script
    (klasifikasi risiko butuh batch_id, tanggal_kadaluwarsa, jumlah_masuk,
    kategori; forecasting cuma butuh jumlah_keluar), supaya query cukup
    ditulis sekali di sini.
    """
    query = """
    SELECT
        f.obat_id,
        o.nama_generik,
        o.obat_kode,
        o.kategori,
        f.gudang_id,
        g.nama AS nama_gudang,
        f.tanggal_id,
        d.tanggal,
        d.hari,
        d.is_weekend,
        f.batch_id,
        f.tanggal_kadaluwarsa,
        f.jumlah_masuk,
        f.jumlah_keluar
    FROM gold.fact_stock_movement f
    JOIN gold.dim_obat o ON f.obat_id = o.obat_id
    JOIN gold.dim_gudang g ON f.gudang_id = g.gudang_id
    JOIN gold.dim_waktu d ON f.tanggal_id = d.tanggal_id
    ORDER BY d.tanggal
    """

    df = pd.read_sql(query, engine)
    df["tanggal"] = pd.to_datetime(df["tanggal"])
    df["tanggal_kadaluwarsa"] = pd.to_datetime(df["tanggal_kadaluwarsa"])

    # dedup, konsisten dengan temuan EDA (6 baris duplikat sempat lolos dari
    # proses transform sisi DE, dampaknya sangat kecil jadi cukup di-drop di sini)
    jumlah_sebelum = len(df)
    df = df.drop_duplicates().reset_index(drop=True)
    jumlah_dibuang = jumlah_sebelum - len(df)
    if jumlah_dibuang > 0:
        print(f"Ditemukan dan dibuang {jumlah_dibuang} baris duplikat persis")

    return df


def hitung_demand_harian_lengkap(df):
    """Agregasi pergerakan stok ke level harian per kombinasi obat-gudang,
    lalu lengkapi kalender penuh (hari tanpa transaksi diisi nol).

    Pengisian nol ini penting karena hari tanpa baris di data mentah bukan
    berarti datanya hilang, tapi memang tidak ada konsumsi/penerimaan di
    hari itu. Kalau tidak dilengkapi, model forecasting dan perhitungan
    rata-rata demand akan bias (seolah-olah hari itu tidak pernah ada).
    """
    demand_harian = (
        df.groupby(["obat_id", "nama_generik", "gudang_id", "nama_gudang", "tanggal"])
        .agg(jumlah_keluar=("jumlah_keluar", "sum"), jumlah_masuk=("jumlah_masuk", "sum"))
        .reset_index()
    )

    tanggal_lengkap = pd.date_range(df["tanggal"].min(), df["tanggal"].max(), freq="D")

    daftar_lengkap = []
    for (obat_id, nama_generik, gudang_id, nama_gudang), grup in demand_harian.groupby(
        ["obat_id", "nama_generik", "gudang_id", "nama_gudang"]
    ):
        grup_lengkap = (
            grup.set_index("tanggal")
            .reindex(tanggal_lengkap)
            .rename_axis("tanggal")
            .reset_index()
        )
        grup_lengkap["obat_id"] = obat_id
        grup_lengkap["nama_generik"] = nama_generik
        grup_lengkap["gudang_id"] = gudang_id
        grup_lengkap["nama_gudang"] = nama_gudang
        grup_lengkap["jumlah_keluar"] = grup_lengkap["jumlah_keluar"].fillna(0)
        grup_lengkap["jumlah_masuk"] = grup_lengkap["jumlah_masuk"].fillna(0)
        daftar_lengkap.append(grup_lengkap)

    return pd.concat(daftar_lengkap, ignore_index=True)
