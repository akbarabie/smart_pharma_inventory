"""
Extractor untuk sumber data e-Fornas Kemkes (Daftar Obat Esensial Nasional).

Script ini didesain untuk membaca file "Daftar Obat.csv" yang sudah disiapkan,
menambahkan metadata asal file untuk jejak audit, lalu menyimpannya sebagai
file mentah untuk bronze layer.

PENTING soal prinsip bronze: extractor ini SENGAJA TIDAK melakukan
pembersihan data (hapus duplikat, generate obat_id, tentukan flag_vital, dst).
Itu semua keputusan transformasi yang tempatnya di tahap Silver, bukan di sini.
Bronze harus tetap apa adanya dari sumber.
"""

import os
from datetime import datetime, timezone
import pandas as pd

from minio_client import upload_file_to_bronze

INPUT_PATH = "../data/raw/fornas/Daftar Obat.csv"
OUTPUT_PATH = "../data/raw/fornas/Daftar Obat_bronze.csv"

# Kolom yang kita harapkan ada di dalam file, berdasarkan hasil inspeksi
KOLOM_DIHARAPKAN = {"Nama Obat", "Nama Obat Internasional"}

def main():
    if not os.path.exists(INPUT_PATH):
        print(f"File {INPUT_PATH} tidak ditemukan. Pastikan file ada di direktori yang sama.")
        return

    print(f"Membaca file: {INPUT_PATH}...")
    
    # Menggunakan separator ';' karena format CSV e-Fornas menggunakan titik koma
    try:
        df = pd.read_csv(INPUT_PATH, sep=";")
    except Exception as e:
        print(f"Gagal membaca file CSV: {e}")
        return

    kolom_ditemukan = set(df.columns)
    if not KOLOM_DIHARAPKAN.issubset(kolom_ditemukan):
        print(f"PERINGATAN: File punya kolom tidak sesuai harapan, proses dihentikan.")
        print(f"  Diharapkan: {KOLOM_DIHARAPKAN}")
        print(f"  Ditemukan : {kolom_ditemukan}")
        return

    # Standardisasi nama kolom
    df = df.rename(columns={
        "Nama Obat": "nama_obat",
        "Nama Obat Internasional": "nama_obat_internasional",
    })

    # Metadata jejak audit: dari file mana baris ini berasal, dan kapan diekstrak.
    # Ini bukan "transformasi data", ini metadata proses ekstraksi, jadi tetap
    # wajar ditambahkan di tahap bronze.
    df["sumber_file"] = os.path.basename(INPUT_PATH)
    df["diekstrak_pada"] = datetime.now(timezone.utc).isoformat()

    print(f"Total baris (sebelum cek duplikat): {len(df)}")

    jumlah_duplikat = df.duplicated(subset=["nama_obat", "nama_obat_internasional"]).sum()
    if jumlah_duplikat > 0:
        print(f"Catatan: ada {jumlah_duplikat} baris dengan nama obat yang sama persis "
              f"muncul lebih dari sekali. INI SENGAJA TIDAK DIHAPUS DI SINI, "
              f"deduplikasi itu tugas tahap Silver, bukan bronze.")

    # Membuat folder tujuan jika belum ada dan menyimpan hasil proses
    os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)
    df.to_csv(OUTPUT_PATH, index=False)
    print(f"\nFile bronze tersimpan di: {OUTPUT_PATH}")

    # Upload ke MinIO (Bronze Layer)
    try:
        upload_file_to_bronze(OUTPUT_PATH, "fornas/daftar_obat.csv")
        print("\nUpload ke MinIO berhasil.")
    except Exception as error:
        print(f"\nUpload ke MinIO gagal: {error}")
        print("File mentahnya tetap aman tersimpan lokal di atas, coba lagi setelah "
              "'docker compose up' jalan dan bucket bronze siap.")

if __name__ == "__main__":
    main()