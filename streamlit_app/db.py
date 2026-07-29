"""
Modul koneksi database dan pengambilan/pengolahan data untuk streamlit_app.

Dipakai lintas halaman (grup Data Scientist maupun Data Analyst), supaya
query dan logika olah data cuma didefinisikan sekali. Semua fungsi
pengambilan data dibungkus st.cache_data supaya Streamlit tidak menjalankan
ulang query berat setiap kali ada interaksi widget (Streamlit menjalankan
ulang seluruh script halaman dari atas di setiap interaksi).
"""

import os

import pandas as pd
import streamlit as st
from dotenv import load_dotenv
from sqlalchemy import create_engine


def ambil_secret(nama_key: str):
    """Baca kredensial dari st.secrets (dipakai saat deploy ke Streamlit
    Community Cloud) dengan fallback ke .env lewat os.getenv (dipakai saat
    development lokal). Supaya kode yang sama jalan di kedua lingkungan
    tanpa perlu diubah manual saat nanti deploy.
    """
    try:
        if nama_key in st.secrets:
            return st.secrets[nama_key]
    except Exception:
        pass
    load_dotenv()
    return os.getenv(nama_key)


@st.cache_resource
def dapatkan_engine():
    """Engine SQLAlchemy dipakai bersama sepanjang siklus hidup aplikasi.

    Pakai st.cache_resource (bukan st.cache_data), karena ini objek koneksi
    yang perlu dipakai ulang, bukan data yang perlu di-refresh berkala.
    """
    db_url = ambil_secret("GOLD_DATABASE_URL")
    if not db_url:
        st.error("GOLD_DATABASE_URL tidak ditemukan, cek .env atau secrets Streamlit Cloud")
        st.stop()
    return create_engine(db_url)


@st.cache_data(ttl=600)
def ambil_daftar_gudang() -> pd.DataFrame:
    engine = dapatkan_engine()
    return pd.read_sql("SELECT gudang_id, nama FROM gold.dim_gudang ORDER BY gudang_id", engine)


@st.cache_data(ttl=600)
def ambil_daftar_obat_operasional() -> pd.DataFrame:
    """Cuma obat yang punya data pergerakan stok (obat operasional), bukan
    seluruh obat Fornas, karena obat lain tidak punya apa pun untuk
    ditampilkan di forecast atau dashboard manapun."""
    engine = dapatkan_engine()
    query = """
        SELECT DISTINCT o.obat_id, o.nama_generik
        FROM gold.dim_obat o
        JOIN gold.fact_stock_movement f ON o.obat_id = f.obat_id
        ORDER BY o.nama_generik
    """
    return pd.read_sql(query, engine)


@st.cache_data(ttl=600)
def ambil_fact_stock_movement() -> pd.DataFrame:
    """Ambil seluruh data pergerakan stok, sudah di-join dengan dimensi
    obat, gudang, dan waktu. Di-cache 10 menit supaya tidak menarik ulang
    puluhan ribu baris tiap ada interaksi widget di halaman mana pun."""
    engine = dapatkan_engine()
    query = """
        SELECT f.obat_id, o.nama_generik, f.gudang_id, g.nama AS nama_gudang,
               d.tanggal, f.batch_id, f.tanggal_kadaluwarsa,
               f.jumlah_masuk, f.jumlah_keluar
        FROM gold.fact_stock_movement f
        JOIN gold.dim_obat o ON f.obat_id = o.obat_id
        JOIN gold.dim_gudang g ON f.gudang_id = g.gudang_id
        JOIN gold.dim_waktu d ON f.tanggal_id = d.tanggal_id
    """
    df = pd.read_sql(query, engine)
    df["tanggal"] = pd.to_datetime(df["tanggal"])
    df["tanggal_kadaluwarsa"] = pd.to_datetime(df["tanggal_kadaluwarsa"])
    return df


@st.cache_data(ttl=600)
def ambil_pred_demand_forecast() -> pd.DataFrame:
    engine = dapatkan_engine()
    query = """
        SELECT p.obat_id, o.nama_generik, p.gudang_id, g.nama AS nama_gudang,
               d.tanggal, p.prediksi_permintaan, p.prediksi_permintaan_bawah,
               p.prediksi_permintaan_atas
        FROM gold.pred_demand_forecast p
        JOIN gold.dim_obat o ON p.obat_id = o.obat_id
        JOIN gold.dim_gudang g ON p.gudang_id = g.gudang_id
        JOIN gold.dim_waktu d ON p.tanggal_id = d.tanggal_id
        ORDER BY d.tanggal
    """
    df = pd.read_sql(query, engine)
    df["tanggal"] = pd.to_datetime(df["tanggal"])
    return df


@st.cache_data(ttl=600)
def ambil_risiko_kadaluwarsa_lengkap() -> pd.DataFrame:
    """Gabungkan skor risiko dengan info batch (obat, gudang, sisa stok,
    tanggal kadaluwarsa) dalam satu query, dipakai baik di halaman DS
    maupun DA."""
    engine = dapatkan_engine()
    query = """
        WITH ringkasan_batch AS (
            SELECT batch_id, obat_id, gudang_id, tanggal_kadaluwarsa,
                   SUM(jumlah_masuk) - SUM(jumlah_keluar) AS sisa_stok
            FROM gold.fact_stock_movement
            GROUP BY batch_id, obat_id, gudang_id, tanggal_kadaluwarsa
        )
        SELECT p.batch_id, p.probabilitas_risiko, p.kategori_risiko,
               r.obat_id, o.nama_generik, r.gudang_id, g.nama AS nama_gudang,
               r.tanggal_kadaluwarsa, r.sisa_stok
        FROM gold.pred_expiry_risk p
        JOIN ringkasan_batch r ON p.batch_id = r.batch_id
        JOIN gold.dim_obat o ON r.obat_id = o.obat_id
        JOIN gold.dim_gudang g ON r.gudang_id = g.gudang_id
        ORDER BY p.probabilitas_risiko DESC
    """
    df = pd.read_sql(query, engine)
    df["tanggal_kadaluwarsa"] = pd.to_datetime(df["tanggal_kadaluwarsa"])
    return df


@st.cache_data(ttl=600)
def ambil_rekomendasi() -> pd.DataFrame:
    engine = dapatkan_engine()
    query = """
        SELECT r.rekomendasi_id, r.obat_id, o.nama_generik, r.gudang_id,
               g.nama AS nama_gudang, r.jenis_rekomendasi, r.narasi,
               r.data_pendukung, r.dibuat_pada
        FROM gold.agent_recommendations r
        JOIN gold.dim_obat o ON r.obat_id = o.obat_id
        JOIN gold.dim_gudang g ON r.gudang_id = g.gudang_id
        ORDER BY r.dibuat_pada DESC
    """
    return pd.read_sql(query, engine)


@st.cache_data(ttl=600)
def hitung_saldo_harian_lengkap() -> pd.DataFrame:
    """Hitung saldo stok berjalan (kumulatif masuk dikurangi keluar) per
    hari, per kombinasi obat-gudang, dengan kalender penuh (hari tanpa
    transaksi diisi nol, bukan hilang dari perhitungan).

    Ini basis untuk metrik service level. Dipisah dari
    ambil_fact_stock_movement dan di-cache terpisah karena komputasinya
    lebih berat (reindex per grup), supaya tidak perlu dihitung ulang kalau
    yang dibutuhkan di tempat lain cuma data mentahnya.
    """
    df = ambil_fact_stock_movement()

    harian = (
        df.groupby(["obat_id", "nama_generik", "gudang_id", "nama_gudang", "tanggal"])
        .agg(jumlah_masuk=("jumlah_masuk", "sum"), jumlah_keluar=("jumlah_keluar", "sum"))
        .reset_index()
    )

    tanggal_lengkap = pd.date_range(df["tanggal"].min(), df["tanggal"].max(), freq="D")

    daftar = []
    for (obat_id, nama_generik, gudang_id, nama_gudang), grup in harian.groupby(
        ["obat_id", "nama_generik", "gudang_id", "nama_gudang"]
    ):
        grup_lengkap = (
            grup.set_index("tanggal").reindex(tanggal_lengkap).rename_axis("tanggal").reset_index()
        )
        grup_lengkap["obat_id"] = obat_id
        grup_lengkap["nama_generik"] = nama_generik
        grup_lengkap["gudang_id"] = gudang_id
        grup_lengkap["nama_gudang"] = nama_gudang
        grup_lengkap["jumlah_masuk"] = grup_lengkap["jumlah_masuk"].fillna(0)
        grup_lengkap["jumlah_keluar"] = grup_lengkap["jumlah_keluar"].fillna(0)
        grup_lengkap["net_harian"] = grup_lengkap["jumlah_masuk"] - grup_lengkap["jumlah_keluar"]
        grup_lengkap["saldo_stok"] = grup_lengkap["net_harian"].cumsum()
        daftar.append(grup_lengkap)

    return pd.concat(daftar, ignore_index=True)


def hitung_service_level(saldo_harian: pd.DataFrame, tanggal_mulai, tanggal_akhir, daftar_gudang=None) -> float:
    """Persentase hari dalam rentang tanggal tertentu di mana saldo stok
    berjalan masih di atas nol, dirata-rata lintas kombinasi obat-gudang
    yang dipilih.

    Ini proxy, bukan ukuran service level yang presisi secara akademis,
    karena data tidak mencatat permintaan yang eksplisit ditolak akibat
    stok habis (generator sintetis cuma mencatat konsumsi aktual). Asumsi
    yang dipakai: kalau saldo stok sudah nol, permintaan di hari itu
    otomatis tidak terpenuhi penuh.
    """
    subset = saldo_harian[
        (saldo_harian["tanggal"] >= tanggal_mulai) & (saldo_harian["tanggal"] <= tanggal_akhir)
    ]
    if daftar_gudang:
        subset = subset[subset["gudang_id"].isin(daftar_gudang)]

    if len(subset) == 0:
        return float("nan")

    return float((subset["saldo_stok"] > 0).mean() * 100)


def hitung_waste_rate_proyeksi(risiko_df: pd.DataFrame, daftar_gudang=None) -> float:
    """Persentase UNIT (bukan Rupiah, karena data harga di luar scope
    project ini, lihat keputusan LKPP) dari sisa stok batch yang masih
    berjalan yang jatuh di kategori risiko Tinggi."""
    subset = risiko_df[risiko_df["sisa_stok"] > 0].copy()
    if daftar_gudang:
        subset = subset[subset["gudang_id"].isin(daftar_gudang)]

    total_sisa_stok = subset["sisa_stok"].sum()
    if total_sisa_stok == 0:
        return float("nan")

    sisa_stok_tinggi = subset[subset["kategori_risiko"] == "Tinggi"]["sisa_stok"].sum()
    return float(sisa_stok_tinggi / total_sisa_stok * 100)
