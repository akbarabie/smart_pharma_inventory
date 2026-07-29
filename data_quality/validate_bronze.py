"""
Data Quality Validation untuk bronze layer, pakai Great Expectations (GX Core 1.x).

Memvalidasi dua dataset:
    1. Daftar Obat_bronze.csv  (gabungan semua huruf Fornas)
    2. stock_movement_synthetic.csv (simulasi stok/batch/expiry)

Filosofi threshold yang dipakai di sini PENTING untuk dipahami, bukan cuma
detail teknis: setiap expectation punya parameter `mostly`, yaitu persentase
minimum baris yang harus lolos supaya expectation itu dianggap SUKSES.

Kita TIDAK menuntut data 100 persen sempurna (mostly=1.0 untuk segala hal),
karena kita sendiri yang sengaja menyuntikkan sedikit noise ke data sintetis
(lihat extractors/generate_synthetic_stock.py). Threshold di bawah ini
disetel sedikit di atas persentase noise yang kita tahu ada, supaya:
    - Kalau noise-nya sesuai perkiraan (data sintetis kita) -> validasi LULUS,
      pipeline lanjut ke Silver, tapi tetap dicatat di laporan.
    - Kalau noise-nya tiba-tiba melonjak jauh di luar perkiraan (indikasi ada
      bug baru atau sumber data berubah) -> validasi GAGAL, pipeline berhenti,
      tidak lanjut ke Silver dengan data yang mencurigakan.

Ini pola yang jauh lebih realistis dibanding validasi "harus 100% bersih",
yang di dunia nyata hampir tidak pernah tercapai untuk data operasional.

Cara pakai:
    python data_quality/validate_bronze.py

Exit code 0 kalau semua validasi (dengan threshold masing-masing) lulus,
exit code 1 kalau ada yang gagal (dipakai Airflow untuk menghentikan DAG).
"""

import json
import os
import sys
from datetime import datetime, timezone

import great_expectations as gx
import pandas as pd

# Referensi kode obat dan gudang yang valid, dipakai untuk mengecek apakah
# ada kode aneh yang tidak dikenal muncul di data. Sengaja diduplikasi dari
# extractors/generate_synthetic_stock.py (bukan di-import) supaya script ini
# tetap berdiri sendiri dan gampang ditest terpisah. Kalau daftar obat/gudang
# berubah di generator, ingat untuk update juga di sini.
VALID_OBAT_KODE = [
    "PCT", "AMX", "AML", "MET", "OMZ", "CAP", "SIM", "SAL", "IBU", "CFT",
    "INS", "ORL", "VTB", "RAN", "DEX", "CFX", "MTZ", "FUR", "GLB", "LOR",
]
VALID_GUDANG_KODE = ["GD01", "GD02", "GD03", "GD04"]

REPORT_DIR = "data_quality/reports"


def buat_context():
    """Bikin GX context sekali, dipakai bersama untuk kedua dataset."""
    return gx.get_context(mode="ephemeral")


def validasi_stock_movement(context, path_csv):
    """
    Validasi dataset simulasi pergerakan stok.
    Threshold mostly disetel berdasarkan noise yang sengaja kita suntik:
        - batch_id kosong: ~2.0%   -> toleransi sampai 3%
        - jumlah_keluar negatif: ~0.29% -> toleransi sampai 0.5%
        - baris duplikat: ~0.48%  -> toleransi sampai 1%
        - format tanggal beda: ~1.0% -> toleransi sampai 2%
    """
    df = pd.read_csv(path_csv)

    data_source = context.data_sources.add_pandas("stock_movement_source")
    data_asset = data_source.add_dataframe_asset(name="stock_movement_asset")
    batch_definition = data_asset.add_batch_definition_whole_dataframe("stock_movement_batch")

    suite = gx.ExpectationSuite(name="stock_movement_suite")

    kolom_diharapkan = {
        "tanggal", "obat_kode", "obat_nama", "gudang_kode", "gudang_nama",
        "batch_id", "tanggal_kadaluwarsa", "jumlah_masuk", "jumlah_keluar",
    }
    suite.add_expectation(gx.expectations.ExpectTableColumnsToMatchSet(column_set=list(kolom_diharapkan)))

    suite.add_expectation(gx.expectations.ExpectColumnValuesToNotBeNull(column="batch_id", mostly=0.97))
    suite.add_expectation(gx.expectations.ExpectColumnValuesToBeBetween(column="jumlah_masuk", min_value=0, mostly=1.0))
    suite.add_expectation(gx.expectations.ExpectColumnValuesToBeBetween(column="jumlah_keluar", min_value=0, mostly=0.995))
    suite.add_expectation(gx.expectations.ExpectColumnValuesToBeInSet(column="obat_kode", value_set=VALID_OBAT_KODE, mostly=1.0))
    suite.add_expectation(gx.expectations.ExpectColumnValuesToBeInSet(column="gudang_kode", value_set=VALID_GUDANG_KODE, mostly=1.0))
    suite.add_expectation(gx.expectations.ExpectColumnValuesToMatchRegex(
        column="tanggal", regex=r"^\d{4}-\d{2}-\d{2}$", mostly=0.98
    ))
    suite.add_expectation(gx.expectations.ExpectColumnValuesToMatchRegex(
        column="tanggal_kadaluwarsa", regex=r"^\d{4}-\d{2}-\d{2}$", mostly=1.0
    ))
    suite.add_expectation(gx.expectations.ExpectCompoundColumnsToBeUnique(
        column_list=list(kolom_diharapkan), mostly=0.99
    ))

    context.suites.add(suite)
    validation_definition = context.validation_definitions.add(
        gx.core.validation_definition.ValidationDefinition(
            name="stock_movement_validation", data=batch_definition, suite=suite
        )
    )
    checkpoint = context.checkpoints.add(
        gx.checkpoint.checkpoint.Checkpoint(
            name="stock_movement_checkpoint", validation_definitions=[validation_definition]
        )
    )
    return checkpoint.run(batch_parameters={"dataframe": df})


def validasi_fornas(context, path_csv):
    """Validasi dataset daftar obat Fornas. Datanya jauh lebih sederhana, jadi
    expectation-nya juga lebih sedikit."""
    df = pd.read_csv(path_csv)

    data_source = context.data_sources.add_pandas("fornas_source")
    data_asset = data_source.add_dataframe_asset(name="fornas_asset")
    batch_definition = data_asset.add_batch_definition_whole_dataframe("fornas_batch")

    suite = gx.ExpectationSuite(name="fornas_suite")

    kolom_diharapkan = {"nama_obat", "nama_obat_internasional", "sumber_file", "diekstrak_pada"}
    suite.add_expectation(gx.expectations.ExpectTableColumnsToMatchSet(column_set=list(kolom_diharapkan)))
    suite.add_expectation(gx.expectations.ExpectColumnValuesToNotBeNull(column="nama_obat", mostly=1.0))
    suite.add_expectation(gx.expectations.ExpectColumnValuesToNotBeNull(column="nama_obat_internasional", mostly=1.0))
    # Nama obat sebaiknya unik, tapi ini INFORMASIONAL (toleransi sampai 5%),
    # karena tidak fatal kalau ada sedikit duplikat lintas file huruf.
    suite.add_expectation(gx.expectations.ExpectColumnValuesToBeUnique(column="nama_obat", mostly=0.95))

    context.suites.add(suite)
    validation_definition = context.validation_definitions.add(
        gx.core.validation_definition.ValidationDefinition(
            name="fornas_validation", data=batch_definition, suite=suite
        )
    )
    checkpoint = context.checkpoints.add(
        gx.checkpoint.checkpoint.Checkpoint(
            name="fornas_checkpoint", validation_definitions=[validation_definition]
        )
    )
    return checkpoint.run(batch_parameters={"dataframe": df})


def cetak_dan_simpan_hasil(nama_dataset, hasil):
    """Cetak ringkasan ke terminal (kebaca jelas di log Airflow), dan simpan
    laporan lengkap sebagai JSON untuk jejak audit."""
    print(f"\n{'=' * 60}")
    print(f"HASIL VALIDASI: {nama_dataset}")
    print(f"{'=' * 60}")

    ringkasan = []
    for validation_result in hasil.run_results.values():
        for r in validation_result.results:
            status = "LULUS" if r.success else "GAGAL"
            persen_bermasalah = r.result.get("unexpected_percent")
            info_persen = f"{persen_bermasalah:.2f}% baris bermasalah" if persen_bermasalah is not None else ""
            print(f"[{status}] {r.expectation_config.type} {info_persen}")
            ringkasan.append({
                "expectation": r.expectation_config.type,
                "kolom": r.expectation_config.kwargs.get("column") or r.expectation_config.kwargs.get("column_list"),
                "success": r.success,
                "unexpected_percent": persen_bermasalah,
            })

    print(f"\nStatus keseluruhan: {'LULUS' if hasil.success else 'GAGAL'}")

    os.makedirs(REPORT_DIR, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    report_path = f"{REPORT_DIR}/{nama_dataset}_{timestamp}.json"
    with open(report_path, "w") as f:
        json.dump({
            "dataset": nama_dataset,
            "waktu_validasi": datetime.now(timezone.utc).isoformat(),
            "success_keseluruhan": hasil.success,
            "detail": ringkasan,
        }, f, indent=2)
    print(f"Laporan lengkap tersimpan di: {report_path}")

    return hasil.success


def main():
    context = buat_context()
    status_per_dataset = {}

    path_fornas = "data/raw/fornas/Daftar Obat_bronze.csv"
    path_stock = "data/raw/stock_synthetic/stock_movement_synthetic.csv"

    if os.path.exists(path_fornas):
        hasil_fornas = validasi_fornas(context, path_fornas)
        status_per_dataset["fornas"] = cetak_dan_simpan_hasil("fornas", hasil_fornas)
    else:
        print(f"\n[FORNAS] TIDAK DITEMUKAN: {path_fornas}")
        print("[FORNAS] Kemungkinan besar task extract_fornas gagal menemukan file sumbernya "
              "(cek apakah Daftar_Obat.csv sudah ada di data/raw/fornas/).")
        status_per_dataset["fornas"] = False

    if os.path.exists(path_stock):
        hasil_stock = validasi_stock_movement(context, path_stock)
        status_per_dataset["stock_movement"] = cetak_dan_simpan_hasil("stock_movement", hasil_stock)
    else:
        print(f"\n[STOCK_MOVEMENT] TIDAK DITEMUKAN: {path_stock}")
        print("[STOCK_MOVEMENT] Kemungkinan besar task generate_synthetic_stock gagal.")
        status_per_dataset["stock_movement"] = False

    print(f"\n{'=' * 60}")
    print("RINGKASAN STATUS PER DATASET")
    print(f"{'=' * 60}")
    for nama, status in status_per_dataset.items():
        print(f"  {nama}: {'LULUS' if status else 'GAGAL'}")

    if not all(status_per_dataset.values()):
        print("\nVALIDASI GAGAL. Pipeline dihentikan, tidak lanjut ke tahap Silver.")
        sys.exit(1)

    print("\nSemua validasi lulus (dalam batas toleransi). Aman lanjut ke tahap Silver.")


if __name__ == "__main__":
    main()