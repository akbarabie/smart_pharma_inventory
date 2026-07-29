"""
Generator data sintetis untuk fact_stock_movement.

Kenapa perlu generate sendiri (bukan download dari Kaggle):
tidak ada dataset publik yang skemanya cocok dengan kebutuhan project ini
(obat_id, gudang_id, batch_id, tanggal_kadaluwarsa, jumlah_masuk, jumlah_keluar
per hari). Detail keputusan ini ada di README dan docs/PRD.

Logika simulasi:
1. Tiap kombinasi (obat, gudang) menerima batch baru secara periodik,
   bukan tiap hari, meniru pola pengadaan riil.
2. Tiap batch punya tanggal kadaluwarsa sendiri (tanggal_terima + masa_simpan).
3. Konsumsi harian mengambil stok dengan logika FEFO (First Expired First Out):
   batch yang paling cepat kadaluwarsa dihabiskan lebih dulu.
4. Kalau ada batch yang kadaluwarsa duluan sebelum habis terpakai, batch itu
   otomatis "hilang" dari ketersediaan (sisa stoknya jadi waste), TANPA kita
   beri label eksplisit di data ini. Label risiko kadaluwarsa itu tugas
   Data Scientist untuk diturunkan sendiri dari histori pergerakan, supaya
   tidak terjadi data leakage saat training model klasifikasi.
5. Di akhir, sebagian kecil baris (kurang lebih 3-4%) sengaja dibuat "kotor"
   (batch_id kosong, format tanggal beda, duplikat, nilai negatif) supaya
   tahap Data Quality Validation di hari ke-3 punya sesuatu yang nyata
   untuk divalidasi.

Cara pakai:
    python extractors/generate_synthetic_stock.py
"""

import os
import random
from datetime import date, timedelta

import numpy as np
import pandas as pd

from minio_client import upload_file_to_bronze

# Seed tetap supaya hasil generate selalu sama tiap dijalankan ulang.
# Penting untuk reproducibility, terutama pas demo/sidang.
SEED = 42
random.seed(SEED)
rng = np.random.default_rng(SEED)

# Rentang waktu histori yang disimulasikan: 2 tahun ke belakang sampai hari ini.
END_DATE = date.today()
START_DATE = END_DATE - timedelta(days=730)

# Master obat: nama generik DIAMBIL PERSIS dari Daftar_Obat.csv (663 obat resmi
# Formularium Nasional), bukan ejaan Inggris/INN, supaya nanti bisa di-join EXACT
# MATCH dengan data Fornas asli di tahap Gold, tanpa perlu fuzzy matching.
# demand_mean = rata-rata konsumsi harian per gudang (satuan unit/hari)
# shelf_life_hari = umur simpan tipikal sejak diterima gudang
OBAT_MASTER = [
    dict(kode="PCT", nama="parasetamol", nama_internasional="paracetamol", bentuk="Tablet 500 mg", kategori="Analgesik-Antipiretik", demand_mean=45, shelf_life_hari=730),
    dict(kode="AMX", nama="amoksisilin", nama_internasional="amoxicillin", bentuk="Kapsul 500 mg", kategori="Antibiotik", demand_mean=30, shelf_life_hari=730),
    dict(kode="AML", nama="amlodipin", nama_internasional="amlodipine", bentuk="Tablet 10 mg", kategori="Antihipertensi", demand_mean=25, shelf_life_hari=1095),
    dict(kode="MET", nama="metformin", nama_internasional="metformin", bentuk="Tablet 500 mg", kategori="Antidiabetes", demand_mean=28, shelf_life_hari=730),
    dict(kode="OMZ", nama="omeprazol", nama_internasional="omeprazole", bentuk="Kapsul 20 mg", kategori="Antasida", demand_mean=20, shelf_life_hari=730),
    dict(kode="CAP", nama="kaptopril", nama_internasional="captopril", bentuk="Tablet 25 mg", kategori="Antihipertensi", demand_mean=22, shelf_life_hari=730),
    dict(kode="SIM", nama="simvastatin", nama_internasional="simvastatin", bentuk="Tablet 20 mg", kategori="Antihiperlipidemia", demand_mean=18, shelf_life_hari=1095),
    dict(kode="SAL", nama="salbutamol", nama_internasional="salbutamol", bentuk="Inhaler 100 mcg", kategori="Bronkodilator", demand_mean=8, shelf_life_hari=545),
    dict(kode="IBU", nama="ibuprofen", nama_internasional="ibuprofen", bentuk="Tablet 400 mg", kategori="Analgesik-Antiinflamasi", demand_mean=26, shelf_life_hari=1095),
    dict(kode="CFT", nama="seftriakson", nama_internasional="ceftriaxone", bentuk="Injeksi 1 g", kategori="Antibiotik", demand_mean=10, shelf_life_hari=365),
    dict(kode="INS", nama="Human Insulin Prandial: insulin regular", nama_internasional="Human Insulin Prandial: regular insulin", bentuk="Injeksi", kategori="Antidiabetes", demand_mean=6, shelf_life_hari=180),
    dict(kode="ORL", nama="garam oralit", nama_internasional="oral rehydration salt", bentuk="Sachet", kategori="Rehidrasi", demand_mean=35, shelf_life_hari=730),
    dict(kode="VTB", nama="vitamin B kompleks mengandung vitamin B1, vitamin B6, vitamin B12", nama_internasional="vitamin complex B contains vitamin B1, vitamin B6, vitamin B12", bentuk="Tablet", kategori="Suplemen", demand_mean=15, shelf_life_hari=1095),
    dict(kode="RAN", nama="ranitidin", nama_internasional="ranitidine", bentuk="Tablet 150 mg", kategori="Antasida", demand_mean=14, shelf_life_hari=730),
    dict(kode="DEX", nama="deksametason", nama_internasional="dexamethasone", bentuk="Tablet 0.5 mg", kategori="Kortikosteroid", demand_mean=12, shelf_life_hari=1095),
    dict(kode="CFX", nama="sefiksim", nama_internasional="cefixime", bentuk="Kapsul 100 mg", kategori="Antibiotik", demand_mean=16, shelf_life_hari=730),
    dict(kode="MTZ", nama="metronidazol", nama_internasional="metronidazole", bentuk="Tablet 500 mg", kategori="Antibiotik", demand_mean=14, shelf_life_hari=730),
    dict(kode="FUR", nama="furosemid", nama_internasional="furosemide", bentuk="Tablet 40 mg", kategori="Diuretik", demand_mean=10, shelf_life_hari=1095),
    dict(kode="GLB", nama="glibenklamid", nama_internasional="glibenclamide", bentuk="Tablet 5 mg", kategori="Antidiabetes", demand_mean=12, shelf_life_hari=1095),
    dict(kode="LOR", nama="loratadin", nama_internasional="loratadine", bentuk="Tablet 10 mg", kategori="Antihistamin", demand_mean=10, shelf_life_hari=1095),
]

# Master gudang: sebaran regional supaya nanti dashboard filter per gudang/wilayah masuk akal
GUDANG_MASTER = [
    dict(kode="GD01", nama="Gudang Farmasi Jakarta Pusat", wilayah="DKI Jakarta"),
    dict(kode="GD02", nama="Gudang Farmasi Surabaya", wilayah="Jawa Timur"),
    dict(kode="GD03", nama="Gudang Farmasi Medan", wilayah="Sumatera Utara"),
    dict(kode="GD04", nama="Gudang Farmasi Makassar", wilayah="Sulawesi Selatan"),
]


def buat_jadwal_kedatangan_batch(obat, start_date, end_date):
    """
    Membuat jadwal kedatangan batch untuk satu kombinasi obat-gudang.
    Interval kedatangan acak 20-40 hari, meniru siklus pengadaan riil
    (tidak ada gudang yang restock tiap hari).
    """
    jadwal = []
    tanggal_sekarang = start_date
    urutan = 1

    while tanggal_sekarang <= end_date:
        interval_hari = rng.integers(20, 40)

        # Jumlah kedatangan disesuaikan supaya cukup untuk menutup kebutuhan
        # selama interval tersebut, plus buffer 10-50 persen
        jumlah_terima = int(obat["demand_mean"] * interval_hari * rng.uniform(1.1, 1.5))

        # Umur simpan bervariasi sedikit antar batch, meniru kondisi nyata
        variasi_umur = rng.integers(-15, 15)
        masa_simpan = max(30, obat["shelf_life_hari"] + variasi_umur)
        tanggal_kadaluwarsa = tanggal_sekarang + timedelta(days=int(masa_simpan))

        jadwal.append({
            "batch_id": f"{obat['kode']}-{tanggal_sekarang:%Y%m%d}-{urutan:02d}",
            "tanggal_terima": tanggal_sekarang,
            "tanggal_kadaluwarsa": tanggal_kadaluwarsa,
            "jumlah_terima": jumlah_terima,
            "sisa": jumlah_terima,
        })

        tanggal_sekarang += timedelta(days=int(interval_hari))
        urutan += 1

    return jadwal


def faktor_musiman(tanggal, hari_ke, total_hari):
    """
    Menghitung faktor pengali permintaan harian:
    - konsumsi turun di akhir pekan (gudang tetap operasi tapi lebih sepi)
    - ada tren naik pelan sepanjang waktu (simulasi permintaan yang tumbuh)
    - sesekali ada lonjakan acak (simulasi wabah/musim penyakit tertentu)
    """
    faktor_akhir_pekan = 0.4 if tanggal.weekday() == 6 else (0.7 if tanggal.weekday() == 5 else 1.0)
    faktor_tren = 1 + 0.15 * (hari_ke / total_hari)

    faktor_lonjakan = 1.0
    if rng.random() < 0.05:
        faktor_lonjakan = rng.uniform(1.5, 3.0)

    return faktor_akhir_pekan * faktor_tren * faktor_lonjakan


def simulasikan_obat_gudang(obat, gudang, start_date, end_date):
    """
    Simulasi penuh untuk satu kombinasi obat-gudang: kedatangan batch,
    konsumsi harian, dan alokasi FEFO. Mengembalikan list baris mentah
    yang nanti digabung jadi satu tabel besar.
    """
    jadwal_kedatangan = buat_jadwal_kedatangan_batch(obat, start_date, end_date)
    jadwal_per_tanggal = {}
    for batch in jadwal_kedatangan:
        jadwal_per_tanggal.setdefault(batch["tanggal_terima"], []).append(batch)

    batch_aktif = []  # batch yang sudah datang dan masih punya sisa stok
    baris_hasil = []
    total_hari = (end_date - start_date).days

    tanggal = start_date
    hari_ke = 0
    while tanggal <= end_date:
        # 1. Batch baru yang datang hari ini masuk ke daftar aktif
        for batch in jadwal_per_tanggal.get(tanggal, []):
            batch_aktif.append(batch)
            baris_hasil.append({
                "tanggal": tanggal,
                "obat_kode": obat["kode"],
                "obat_nama": obat["nama"],
                "gudang_kode": gudang["kode"],
                "gudang_nama": gudang["nama"],
                "batch_id": batch["batch_id"],
                "tanggal_kadaluwarsa": batch["tanggal_kadaluwarsa"],
                "jumlah_masuk": batch["jumlah_terima"],
                "jumlah_keluar": 0,
            })

        # 2. Buang batch yang sudah lewat tanggal kadaluwarsa (sisa jadi waste,
        #    tidak lagi tersedia untuk dikonsumsi)
        batch_aktif = [b for b in batch_aktif if b["tanggal_kadaluwarsa"] >= tanggal]

        # 3. Urutkan FEFO: batch yang paling cepat kadaluwarsa duluan dipakai
        batch_aktif.sort(key=lambda b: b["tanggal_kadaluwarsa"])

        # 4. Hitung kebutuhan konsumsi hari ini, lalu alokasikan ke batch aktif
        lam = obat["demand_mean"] * faktor_musiman(tanggal, hari_ke, total_hari)
        kebutuhan_hari_ini = int(rng.poisson(lam=max(lam, 0.1)))

        for batch in batch_aktif:
            if kebutuhan_hari_ini <= 0:
                break
            ambil = min(batch["sisa"], kebutuhan_hari_ini)
            if ambil <= 0:
                continue
            batch["sisa"] -= ambil
            kebutuhan_hari_ini -= ambil
            baris_hasil.append({
                "tanggal": tanggal,
                "obat_kode": obat["kode"],
                "obat_nama": obat["nama"],
                "gudang_kode": gudang["kode"],
                "gudang_nama": gudang["nama"],
                "batch_id": batch["batch_id"],
                "tanggal_kadaluwarsa": batch["tanggal_kadaluwarsa"],
                "jumlah_masuk": 0,
                "jumlah_keluar": ambil,
            })

        # 5. Buang batch yang sudah habis dari daftar aktif
        batch_aktif = [b for b in batch_aktif if b["sisa"] > 0]

        tanggal += timedelta(days=1)
        hari_ke += 1

    return baris_hasil


def injeksi_masalah_kualitas_data(df):
    """
    Sengaja merusak sebagian kecil baris supaya tahap Data Quality Validation
    (hari ke-3) punya kasus nyata untuk ditangkap. Total sekitar 3-4% baris
    kena, sisanya tetap bersih.
    """
    df = df.copy()
    n = len(df)

    # 2% baris: batch_id kosong (staf lupa catat nomor batch)
    idx_batch_kosong = rng.choice(n, size=int(n * 0.02), replace=False)
    df.loc[idx_batch_kosong, "batch_id"] = None

    # 0.5% baris: duplikat persis (simulasi double-submit form)
    idx_duplikat = rng.choice(n, size=int(n * 0.005), replace=False)
    df = pd.concat([df, df.loc[idx_duplikat]], ignore_index=True)

    # 0.3% baris: jumlah_keluar jadi negatif (human error input, mustahil tapi realistis)
    kandidat_negatif = df.index[df["jumlah_keluar"] > 0]
    idx_negatif = rng.choice(kandidat_negatif, size=int(len(kandidat_negatif) * 0.003), replace=False)
    df.loc[idx_negatif, "jumlah_keluar"] = -df.loc[idx_negatif, "jumlah_keluar"]

    return df


def main():
    print("Mulai generate data sintetis pergerakan stok...")
    print(f"Rentang tanggal: {START_DATE} sampai {END_DATE}")

    semua_baris = []
    for obat in OBAT_MASTER:
        for gudang in GUDANG_MASTER:
            semua_baris.extend(simulasikan_obat_gudang(obat, gudang, START_DATE, END_DATE))

    df = pd.DataFrame(semua_baris)
    df = df.sort_values(["tanggal", "gudang_kode", "obat_kode"]).reset_index(drop=True)

    print(f"Total baris sebelum injeksi masalah data: {len(df):,}")
    df = injeksi_masalah_kualitas_data(df)
    print(f"Total baris setelah injeksi masalah data: {len(df):,}")

    # Sengaja simpan tanggal sebagai string, sebagian dengan format berbeda,
    # supaya format tanggal yang tidak konsisten juga jadi kasus nyata untuk
    # divalidasi di tahap Silver.
    idx_format_beda = rng.choice(df.index, size=int(len(df) * 0.01), replace=False)

    df["tanggal"] = df["tanggal"].astype(str)
    df["tanggal_kadaluwarsa"] = df["tanggal_kadaluwarsa"].astype(str)
    df.loc[idx_format_beda, "tanggal"] = pd.to_datetime(
        df.loc[idx_format_beda, "tanggal"]
    ).dt.strftime("%d/%m/%Y")

    output_dir = "data/raw/stock_synthetic"
    os.makedirs(output_dir, exist_ok=True)
    output_path = f"{output_dir}/stock_movement_synthetic.csv"
    df.to_csv(output_path, index=False)

    print(f"Selesai. File tersimpan di: {output_path}")
    print("\nContoh 5 baris pertama:")
    print(df.head().to_string())

    try:
        upload_file_to_bronze(output_path, "stock_movement/stock_movement_synthetic.csv")
    except Exception as error:
        print(f"\nUpload ke MinIO gagal: {error}")
        print("File mentahnya tetap aman tersimpan lokal di atas, coba lagi setelah "
              "'docker compose up' jalan dan bucket bronze siap.")


if __name__ == "__main__":
    main()
