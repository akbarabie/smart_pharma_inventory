"""
Fungsi-fungsi query yang disediakan ke chatbot Q&A lewat function calling
Gemini. Ini SATU-SATUNYA cara chatbot mengakses data, bukan text-to-SQL
bebas, sesuai keputusan keamanan di PRD section 5.2. LLM cuma boleh memilih
fungsi mana yang relevan dan mengisi parameternya, query SQL di baliknya
sudah diparameterisasi dan tetap (tidak bisa diubah LLM).

Setiap fungsi mengembalikan list of dict (bukan DataFrame), supaya gampang
diserialize otomatis oleh SDK google-genai saat dikirim balik ke model
sebagai hasil pemanggilan fungsi.

Konvensi parameter gudang_id: default "" (string kosong), BUKAN None, karena
sebagian model function-calling kesulitan menangani None/null di JSON schema.
String kosong berarti "user tidak menyebut gudang spesifik", dan itu berarti
hasil ditampilkan AGREGAT LINTAS SEMUA GUDANG, bukan diam-diam cuma satu
gudang tertentu. Ini keputusan sadar, karena kalau chatbot diam-diam cuma
menjawab dari satu gudang saja tanpa bilang, itu bisa menyesatkan tim
procurement yang mengira jawabannya sudah mencakup semua gudang.
"""

import os

from dotenv import load_dotenv
from sqlalchemy import create_engine, text

_ENGINE = None


def _dapatkan_engine():
    """Lazy singleton, koneksi database cuma dibuat sekali per proses,
    bukan setiap kali salah satu fungsi tool ini dipanggil."""
    global _ENGINE
    if _ENGINE is None:
        load_dotenv()
        db_url = os.getenv("GOLD_DATABASE_URL")
        if not db_url:
            raise RuntimeError("GOLD_DATABASE_URL tidak ditemukan di .env")
        _ENGINE = create_engine(db_url)
    return _ENGINE


def get_expiring_batches(jangka_hari: int = 30, gudang_id: str = "") -> list[dict]:
    """Cari batch obat yang akan kadaluwarsa dalam rentang hari tertentu ke depan.

    Args:
        jangka_hari: jumlah hari ke depan yang mau dicek, default 30 hari
        gudang_id: kode gudang untuk filter, misal 'GD01'. Kosongkan ("")
            kalau user tidak menyebut gudang spesifik di pertanyaannya

    Returns:
        List baris berisi nama_generik, nama_gudang, batch_id, sisa_stok,
        dan tanggal_kadaluwarsa, diurutkan dari yang paling dekat kadaluwarsa
    """
    engine = _dapatkan_engine()
    query = text(
        """
        WITH ringkasan_batch AS (
            SELECT batch_id, obat_id, gudang_id, tanggal_kadaluwarsa,
                   SUM(jumlah_masuk) - SUM(jumlah_keluar) AS sisa_stok
            FROM gold.fact_stock_movement
            GROUP BY batch_id, obat_id, gudang_id, tanggal_kadaluwarsa
        )
        SELECT o.nama_generik, g.nama AS nama_gudang, r.batch_id,
               r.sisa_stok, r.tanggal_kadaluwarsa
        FROM ringkasan_batch r
        JOIN gold.dim_obat o ON r.obat_id = o.obat_id
        JOIN gold.dim_gudang g ON r.gudang_id = g.gudang_id
        WHERE r.sisa_stok > 0
          AND r.tanggal_kadaluwarsa
              BETWEEN CURRENT_DATE AND CURRENT_DATE + make_interval(days => :jangka_hari)
          AND (:gudang_id = '' OR r.gudang_id = :gudang_id)
        ORDER BY r.tanggal_kadaluwarsa ASC
        LIMIT 50
        """
    )
    with engine.connect() as koneksi:
        hasil = koneksi.execute(query, {"jangka_hari": jangka_hari, "gudang_id": gudang_id})
        baris = [dict(r._mapping) for r in hasil]

    for b in baris:
        b["tanggal_kadaluwarsa"] = b["tanggal_kadaluwarsa"].strftime("%Y-%m-%d")
        b["sisa_stok"] = int(b["sisa_stok"])

    if len(baris) == 0:
        return [{"pesan": "Tidak ada batch yang kadaluwarsa dalam rentang waktu tersebut"}]
    return baris


def get_stock_level(nama_obat: str, gudang_id: str = "") -> list[dict]:
    """Cek jumlah stok saat ini untuk obat tertentu.

    Args:
        nama_obat: nama obat dalam bahasa Indonesia, boleh sebagian dan
            tidak case-sensitive, misal 'parasetamol' atau 'amoksisilin'
        gudang_id: kode gudang untuk filter, misal 'GD01'. Kosongkan ("")
            untuk melihat stok di semua gudang

    Returns:
        List baris berisi nama_generik, nama_gudang, dan stok_saat_ini
    """
    engine = _dapatkan_engine()
    query = text(
        """
        SELECT o.nama_generik, g.nama AS nama_gudang,
               SUM(f.jumlah_masuk) - SUM(f.jumlah_keluar) AS stok_saat_ini
        FROM gold.fact_stock_movement f
        JOIN gold.dim_obat o ON f.obat_id = o.obat_id
        JOIN gold.dim_gudang g ON f.gudang_id = g.gudang_id
        WHERE o.nama_generik ILIKE :pola_nama
          AND (:gudang_id = '' OR f.gudang_id = :gudang_id)
        GROUP BY o.nama_generik, g.nama
        ORDER BY g.nama
        """
    )
    with engine.connect() as koneksi:
        hasil = koneksi.execute(query, {"pola_nama": f"%{nama_obat}%", "gudang_id": gudang_id})
        baris = [dict(r._mapping) for r in hasil]

    for b in baris:
        b["stok_saat_ini"] = int(b["stok_saat_ini"])

    if len(baris) == 0:
        return [{"pesan": f"Obat dengan nama mengandung '{nama_obat}' tidak ditemukan di data"}]
    return baris


def get_top_risk_items(n: int = 10, gudang_id: str = "") -> list[dict]:
    """Ambil daftar batch dengan probabilitas risiko kadaluwarsa tertinggi.

    Args:
        n: jumlah batch teratas yang ditampilkan, default 10
        gudang_id: kode gudang untuk filter, misal 'GD01'. Kosongkan ("")
            untuk melihat lintas semua gudang

    Returns:
        List baris berisi nama_generik, nama_gudang, batch_id, sisa_stok,
        probabilitas_risiko, dan kategori_risiko, diurutkan dari yang
        paling berisiko
    """
    engine = _dapatkan_engine()
    query = text(
        """
        WITH ringkasan_batch AS (
            SELECT batch_id, obat_id, gudang_id, tanggal_kadaluwarsa,
                   SUM(jumlah_masuk) - SUM(jumlah_keluar) AS sisa_stok
            FROM gold.fact_stock_movement
            GROUP BY batch_id, obat_id, gudang_id, tanggal_kadaluwarsa
        )
        SELECT o.nama_generik, g.nama AS nama_gudang, r.batch_id, r.sisa_stok,
               p.probabilitas_risiko, p.kategori_risiko
        FROM gold.pred_expiry_risk p
        JOIN ringkasan_batch r ON p.batch_id = r.batch_id
        JOIN gold.dim_obat o ON r.obat_id = o.obat_id
        JOIN gold.dim_gudang g ON r.gudang_id = g.gudang_id
        WHERE r.sisa_stok > 0
          AND (:gudang_id = '' OR r.gudang_id = :gudang_id)
        ORDER BY p.probabilitas_risiko DESC
        LIMIT :n
        """
    )
    with engine.connect() as koneksi:
        hasil = koneksi.execute(query, {"n": n, "gudang_id": gudang_id})
        baris = [dict(r._mapping) for r in hasil]

    for b in baris:
        b["sisa_stok"] = int(b["sisa_stok"])
        b["probabilitas_risiko"] = round(float(b["probabilitas_risiko"]), 4)
    return baris
