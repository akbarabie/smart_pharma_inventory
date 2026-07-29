"""
Transform Silver -> Gold.

Di sinilah dimensional modeling (star schema) beneran dibuat: surrogate key
(obat_id, gudang_id, tanggal_id) di-generate, dan fact table dibuat dengan
mereferensikan dim table lewat foreign key.

Kenapa obat_id/gudang_id/tanggal_id BARU dibuat di sini (bukan di Silver):
generate surrogate key itu keputusan dimensional modeling, butuh join lintas
sumber (Fornas + data operasional), jadi memang tempatnya di Gold, bukan Silver
yang tugasnya cuma bersihkan data per sumber secara independen.

Desain dim_obat:
    Basis utama dim_obat adalah SELURUH 663 obat di Fornas (sumber resmi paling
    lengkap yang kita punya). Obat yang JUGA dipakai di simulasi stok gudang
    (20 obat) di-enrich dengan kategori dan bentuk sediaan (informasi ini
    murni internal, dari desain generator simulasi kita sendiri, BUKAN dari
    Fornas, makanya nilainya NULL untuk 643 obat Fornas lainnya yang belum
    dipakai di simulasi).

    flag_vital = True untuk semua baris, karena basisnya memang dari Fornas
    (daftar obat esensial), semua by definition sudah tergolong vital.

dim_gudang: gudang_id dipakai langsung dari kode gudang (GD01-GD04), tidak
    perlu surrogate key terpisah karena dimension ini kecil dan stabil.

dim_waktu: dibuat mencakup seluruh rentang tanggal yang ada di data stock
    movement (bukan rentang sembarang), classic date dimension.

pred_demand_forecast dan pred_expiry_risk: SENGAJA dibuat kosong di sini.
    Ini kontrak skema untuk Data Scientist mengisi hasil model nanti
    (forecasting dan klasifikasi risiko kadaluwarsa), bukan tugas DE mengisi
    datanya.

fact_procurement_price dan dim_supplier TIDAK dibuat sama sekali, sesuai
    keputusan sebelumnya soal LKPP di luar scope MVP (lihat README).

Idempotent: TRUNCATE fact dulu (child), baru dim (parent), baru insert
ulang dim lalu fact, supaya foreign key constraint tidak dilanggar dan
tidak ada duplikasi data walau dijalankan berkali-kali.

Cara pakai:
    python transform/transform_to_gold.py
"""

import os

import pandas as pd
import psycopg2
from dotenv import load_dotenv
from psycopg2.extras import execute_values

load_dotenv()

# Referensi obat operasional (20 obat yang dipakai simulasi stok), untuk
# enrichment kategori/bentuk_sediaan di dim_obat. Sengaja diduplikasi dari
# extractors/generate_synthetic_stock.py (bukan di-import), supaya script ini
# tetap berdiri sendiri dan gampang ditest terpisah. Kalau OBAT_MASTER di
# generator berubah, ingat update juga di sini.
OBAT_MASTER = [
    dict(kode="PCT", nama="parasetamol", bentuk="Tablet 500 mg", kategori="Analgesik-Antipiretik"),
    dict(kode="AMX", nama="amoksisilin", bentuk="Kapsul 500 mg", kategori="Antibiotik"),
    dict(kode="AML", nama="amlodipin", bentuk="Tablet 10 mg", kategori="Antihipertensi"),
    dict(kode="MET", nama="metformin", bentuk="Tablet 500 mg", kategori="Antidiabetes"),
    dict(kode="OMZ", nama="omeprazol", bentuk="Kapsul 20 mg", kategori="Antasida"),
    dict(kode="CAP", nama="kaptopril", bentuk="Tablet 25 mg", kategori="Antihipertensi"),
    dict(kode="SIM", nama="simvastatin", bentuk="Tablet 20 mg", kategori="Antihiperlipidemia"),
    dict(kode="SAL", nama="salbutamol", bentuk="Inhaler 100 mcg", kategori="Bronkodilator"),
    dict(kode="IBU", nama="ibuprofen", bentuk="Tablet 400 mg", kategori="Analgesik-Antiinflamasi"),
    dict(kode="CFT", nama="seftriakson", bentuk="Injeksi 1 g", kategori="Antibiotik"),
    dict(kode="INS", nama="Human Insulin Prandial: insulin regular", bentuk="Injeksi", kategori="Antidiabetes"),
    dict(kode="ORL", nama="garam oralit", bentuk="Sachet", kategori="Rehidrasi"),
    dict(kode="VTB", nama="vitamin B kompleks mengandung vitamin B1, vitamin B6, vitamin B12", bentuk="Tablet", kategori="Suplemen"),
    dict(kode="RAN", nama="ranitidin", bentuk="Tablet 150 mg", kategori="Antasida"),
    dict(kode="DEX", nama="deksametason", bentuk="Tablet 0.5 mg", kategori="Kortikosteroid"),
    dict(kode="CFX", nama="sefiksim", bentuk="Kapsul 100 mg", kategori="Antibiotik"),
    dict(kode="MTZ", nama="metronidazol", bentuk="Tablet 500 mg", kategori="Antibiotik"),
    dict(kode="FUR", nama="furosemid", bentuk="Tablet 40 mg", kategori="Diuretik"),
    dict(kode="GLB", nama="glibenklamid", bentuk="Tablet 5 mg", kategori="Antidiabetes"),
    dict(kode="LOR", nama="loratadin", bentuk="Tablet 10 mg", kategori="Antihistamin"),
]

GUDANG_MASTER = [
    dict(kode="GD01", nama="Gudang Farmasi Jakarta Pusat", wilayah="DKI Jakarta"),
    dict(kode="GD02", nama="Gudang Farmasi Surabaya", wilayah="Jawa Timur"),
    dict(kode="GD03", nama="Gudang Farmasi Medan", wilayah="Sumatera Utara"),
    dict(kode="GD04", nama="Gudang Farmasi Makassar", wilayah="Sulawesi Selatan"),
]

HARI_INDONESIA = ["Senin", "Selasa", "Rabu", "Kamis", "Jumat", "Sabtu", "Minggu"]


def get_pg_connection():
    database_url = os.getenv("GOLD_DATABASE_URL")
    if not database_url:
        raise RuntimeError("GOLD_DATABASE_URL belum diset di .env")
    return psycopg2.connect(database_url)


def buat_schema_dan_tabel(conn):
    with conn.cursor() as cur:
        cur.execute("""
            CREATE SCHEMA IF NOT EXISTS gold;

            CREATE TABLE IF NOT EXISTS gold.dim_waktu (
                tanggal_id INTEGER PRIMARY KEY,
                tanggal DATE NOT NULL,
                hari TEXT,
                bulan INTEGER,
                tahun INTEGER,
                is_weekend BOOLEAN
            );

            CREATE TABLE IF NOT EXISTS gold.dim_gudang (
                gudang_id TEXT PRIMARY KEY,
                nama TEXT,
                wilayah TEXT
            );

            CREATE TABLE IF NOT EXISTS gold.dim_obat (
                obat_id TEXT PRIMARY KEY,
                nama_generik TEXT,
                nama_obat_internasional TEXT,
                obat_kode TEXT,
                kategori TEXT,
                bentuk_sediaan TEXT,
                flag_vital BOOLEAN
            );

            CREATE TABLE IF NOT EXISTS gold.fact_stock_movement (
                obat_id TEXT REFERENCES gold.dim_obat(obat_id),
                gudang_id TEXT REFERENCES gold.dim_gudang(gudang_id),
                tanggal_id INTEGER REFERENCES gold.dim_waktu(tanggal_id),
                batch_id TEXT,
                tanggal_kadaluwarsa DATE,
                jumlah_masuk INTEGER,
                jumlah_keluar INTEGER
            );

            -- Kontrak skema untuk Data Scientist, sengaja dibiarkan kosong di sini
            CREATE TABLE IF NOT EXISTS gold.pred_demand_forecast (
                obat_id TEXT,
                gudang_id TEXT,
                tanggal_id INTEGER,
                prediksi_permintaan NUMERIC,
                dibuat_pada TIMESTAMPTZ DEFAULT now()
            );

            CREATE TABLE IF NOT EXISTS gold.pred_expiry_risk (
                batch_id TEXT,
                probabilitas_risiko NUMERIC,
                kategori_risiko TEXT,
                dibuat_pada TIMESTAMPTZ DEFAULT now()
            );
        """)
    conn.commit()
    print("Schema dan tabel gold siap.")


def baca_silver(conn, query):
    return pd.read_sql(query, conn)


def bangun_dim_obat(conn):
    df_fornas = baca_silver(conn, "SELECT nama_obat, nama_obat_internasional FROM silver.stg_obat")
    df_operasional = pd.DataFrame(OBAT_MASTER)

    df_fornas["kunci_join"] = df_fornas["nama_obat"].str.lower().str.strip()
    df_operasional["kunci_join"] = df_operasional["nama"].str.lower().str.strip()

    df = df_fornas.merge(
        df_operasional[["kode", "kategori", "bentuk", "kunci_join"]],
        on="kunci_join", how="left",
    )

    df = df.sort_values("nama_obat").reset_index(drop=True)
    df["obat_id"] = [f"OBT{i+1:04d}" for i in range(len(df))]
    df["flag_vital"] = True

    df = df.rename(columns={
        "nama_obat": "nama_generik",
        "kode": "obat_kode",
        "bentuk": "bentuk_sediaan",
    })

    kolom = ["obat_id", "nama_generik", "nama_obat_internasional", "obat_kode",
             "kategori", "bentuk_sediaan", "flag_vital"]

    jumlah_enriched = df["obat_kode"].notna().sum()
    print(f"dim_obat: {len(df)} total obat, {jumlah_enriched} di antaranya "
          f"ter-enrich kategori/bentuk_sediaan (dipakai di simulasi stok)")

    with conn.cursor() as cur:
        cur.execute("TRUNCATE TABLE gold.fact_stock_movement")  # child dulu
        cur.execute("TRUNCATE TABLE gold.dim_obat CASCADE")
        execute_values(cur, f"INSERT INTO gold.dim_obat ({', '.join(kolom)}) VALUES %s",
                       df[kolom].values.tolist())
    conn.commit()
    print(f"gold.dim_obat: {len(df)} baris dimuat")

    return df[["obat_id", "obat_kode"]]


def bangun_dim_gudang(conn):
    df = pd.DataFrame(GUDANG_MASTER)
    df = df.rename(columns={"kode": "gudang_id"})
    kolom = ["gudang_id", "nama", "wilayah"]

    with conn.cursor() as cur:
        cur.execute("TRUNCATE TABLE gold.dim_gudang CASCADE")
        execute_values(cur, f"INSERT INTO gold.dim_gudang ({', '.join(kolom)}) VALUES %s",
                       df[kolom].values.tolist())
    conn.commit()
    print(f"gold.dim_gudang: {len(df)} baris dimuat")


def bangun_dim_waktu(conn):
    rentang = baca_silver(conn, "SELECT MIN(tanggal) AS mulai, MAX(tanggal) AS akhir FROM silver.stg_stock_movement")
    mulai, akhir = rentang.loc[0, "mulai"], rentang.loc[0, "akhir"]

    tanggal_range = pd.date_range(mulai, akhir, freq="D")
    df = pd.DataFrame({"tanggal": tanggal_range})
    df["tanggal_id"] = df["tanggal"].dt.strftime("%Y%m%d").astype(int)
    df["hari"] = df["tanggal"].dt.weekday.map(lambda i: HARI_INDONESIA[i])
    df["bulan"] = df["tanggal"].dt.month
    df["tahun"] = df["tanggal"].dt.year
    df["is_weekend"] = df["tanggal"].dt.weekday.isin([5, 6])

    kolom = ["tanggal_id", "tanggal", "hari", "bulan", "tahun", "is_weekend"]
    with conn.cursor() as cur:
        cur.execute("TRUNCATE TABLE gold.dim_waktu CASCADE")
        execute_values(cur, f"INSERT INTO gold.dim_waktu ({', '.join(kolom)}) VALUES %s",
                       df[kolom].values.tolist())
    conn.commit()
    print(f"gold.dim_waktu: {len(df)} baris dimuat ({mulai} s.d. {akhir})")


def bangun_fact_stock_movement(conn, obat_lookup):
    df = baca_silver(conn, "SELECT * FROM silver.stg_stock_movement")

    obat_lookup = obat_lookup.dropna(subset=["obat_kode"]).rename(columns={"obat_kode": "obat_kode_lookup"})
    df = df.merge(obat_lookup, left_on="obat_kode", right_on="obat_kode_lookup", how="left")

    tidak_ketemu = df["obat_id"].isna().sum()
    if tidak_ketemu > 0:
        print(f"PERINGATAN: {tidak_ketemu} baris fact tidak ketemu obat_id-nya, akan dibuang.")
        df = df.dropna(subset=["obat_id"])

    df["gudang_id"] = df["gudang_kode"]
    df["tanggal_id"] = pd.to_datetime(df["tanggal"]).dt.strftime("%Y%m%d").astype(int)

    kolom = ["obat_id", "gudang_id", "tanggal_id", "batch_id",
             "tanggal_kadaluwarsa", "jumlah_masuk", "jumlah_keluar"]

    with conn.cursor() as cur:
        cur.execute("TRUNCATE TABLE gold.fact_stock_movement")
        execute_values(cur, f"INSERT INTO gold.fact_stock_movement ({', '.join(kolom)}) VALUES %s",
                       df[kolom].values.tolist())
    conn.commit()
    print(f"gold.fact_stock_movement: {len(df)} baris dimuat")


def main():
    conn = get_pg_connection()
    try:
        buat_schema_dan_tabel(conn)
        obat_lookup = bangun_dim_obat(conn)
        bangun_dim_gudang(conn)
        bangun_dim_waktu(conn)
        bangun_fact_stock_movement(conn, obat_lookup)
    finally:
        conn.close()
    print("\nTransform ke Gold selesai.")


if __name__ == "__main__":
    main()
