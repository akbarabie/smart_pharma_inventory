"""
Procurement Recommendation Generator.

Agent yang membaca gold.pred_expiry_risk dan gold.pred_demand_forecast,
menentukan jenis tindakan yang disarankan berdasarkan angka aktual, lalu
memanggil LLM (Google Gemini API) cuma untuk merangkai angka itu jadi
narasi Bahasa Indonesia yang enak dibaca tim procurement. Hasilnya
disimpan ke gold.agent_recommendations.

Kenapa Gemini, bukan Claude/OpenAI seperti draft awal PRD: project ini
tidak ada budget (final project bootcamp), sementara Claude API dan
OpenAI API tidak punya tier gratis yang bisa diandalkan untuk pemakaian
berkelanjutan. Google Gemini API menyediakan free tier resmi tanpa kartu
kredit dengan limit yang jauh lebih dari cukup untuk kebutuhan project
ini. Ini keputusan sadar, didokumentasikan di README sebagai deviasi
dari draft PRD, bukan disembunyikan.

Prinsip anti-halusinasi (wajib, sesuai PRD section 5.1): LLM CUMA
bertugas merangkai angka yang sudah dihitung program jadi narasi bahasa
natural. Semua angka (SKU, sisa stok, hari menuju kadaluwarsa,
probabilitas risiko, demand gudang lain) dan JENIS rekomendasi
(redistribusi/diskon_cepat/prioritas_fefo) ditentukan lebih dulu oleh
fungsi tentukan_jenis_rekomendasi() berbasis data aktual. LLM tidak
pernah diminta menghitung ulang angka apapun, cuma menulis ulang jadi
kalimat.
"""

import json
import os
import sys
import time
import warnings
from datetime import date

import pandas as pd
from dotenv import load_dotenv
from google import genai
from google.genai import errors, types
from sqlalchemy import text

warnings.filterwarnings("ignore")

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "models"))
from common import buat_koneksi_database  # noqa: E402

# batasi jumlah rekomendasi per kali jalan, fokus ke risiko paling mendesak.
# angka 15 dipilih supaya aman dari rate limit free tier (5 RPM per model,
# artinya 15 panggilan berturut-turut butuh sekitar 2-3 menit dengan jeda,
# masih wajar untuk job terjadwal) dan tetap actionable buat tim procurement
# (361 batch berisiko Tinggi jelas tidak mungkin ditindaklanjuti sekaligus)
# Defaultnya 15, untuk mencoba cukup 2 untuk hemat RPD
MAKS_REKOMENDASI_PER_RUN = 15

# free tier gemini-3.6-flash dibatasi 5 request per menit (RPM), artinya
# rata-rata harus ada jeda minimal 12 detik antar panggilan. Dikasih buffer
# jadi 13 detik supaya tidak mepet-mepet kena limit karena selisih waktu
# proses di sisi kita sendiri (query, susun prompt, dsb)
JEDA_ANTAR_PANGGILAN_DETIK = 13

# kalau tetap kena rate limit meski sudah dikasih jeda (misal karena quota
# ini kepakai bareng proses lain di project Google yang sama), coba ulang
# beberapa kali sebelum benar-benar menyerah untuk batch itu
MAKS_PERCOBAAN_ULANG = 4

# ambang aturan penentuan jenis rekomendasi
AMBANG_HARI_MEPET = 14  # di bawah ini, dianggap terlalu mepet untuk redistribusi
FAKTOR_DEMAND_LEBIH_TINGGI = 1.5  # gudang tujuan harus demand-nya jauh lebih tinggi

# gemini-3.6-flash: GA (stabil) per 21 Juli 2026, rate limit free tier sama
# dengan 2.5 Flash tapi lebih baru, lebih murah, dan lebih hemat token.
# Dibuat configurable lewat .env supaya gampang ganti kalau ada model baru lagi.
NAMA_MODEL_GEMINI = os.getenv("GEMINI_MODEL", "gemini-3.6-flash")

SYSTEM_INSTRUCTION = """
Kamu adalah asisten procurement gudang farmasi. Tugasmu cuma satu: merangkai
angka yang diberikan menjadi narasi rekomendasi singkat dalam Bahasa Indonesia
yang natural dan profesional, 3-4 kalimat.

Aturan wajib:
- JANGAN mengarang, mengubah, atau menghitung ulang angka apapun, pakai persis
  angka yang diberikan di prompt.
- JANGAN menambahkan jenis tindakan lain di luar yang sudah ditentukan.
- Tulis seolah kamu sedang memberi laporan singkat ke kepala gudang, bukan
  ke sesama sistem.
- Jangan pakai emoji atau tanda baca berlebihan.
"""


def buat_klien_gemini():
    """Baca API key dari .env dan buat klien Gemini.

    Wajib dijalankan dari root repo supaya python-dotenv menemukan .env.
    """
    load_dotenv()
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError(
            "GEMINI_API_KEY tidak ditemukan di .env, "
            "buat dulu API key gratis di Google AI Studio lalu isi ke .env"
        )
    return genai.Client(api_key=api_key)


def ambil_batch_berisiko_tinggi(engine):
    """Ambil batch dengan kategori_risiko Tinggi, lengkap dengan sisa stok
    aktual dan identitas obat/gudang. Sisa stok dihitung langsung dari
    fact_stock_movement, bukan dari tabel prediksi, karena tabel prediksi
    cuma menyimpan skor risiko, bukan angka stok."""
    query = """
    SELECT
        r.batch_id,
        r.probabilitas_risiko,
        f.obat_id,
        o.nama_generik,
        o.obat_kode,
        f.gudang_id,
        g.nama AS nama_gudang,
        f.tanggal_kadaluwarsa,
        SUM(f.jumlah_masuk) - SUM(f.jumlah_keluar) AS sisa_stok
    FROM gold.pred_expiry_risk r
    JOIN gold.fact_stock_movement f ON r.batch_id = f.batch_id
    JOIN gold.dim_obat o ON f.obat_id = o.obat_id
    JOIN gold.dim_gudang g ON f.gudang_id = g.gudang_id
    WHERE r.kategori_risiko = 'Tinggi'
    GROUP BY r.batch_id, r.probabilitas_risiko, f.obat_id, o.nama_generik,
             o.obat_kode, f.gudang_id, g.nama, f.tanggal_kadaluwarsa
    ORDER BY r.probabilitas_risiko DESC
    LIMIT :maks
    """
    df = pd.read_sql(text(query), engine, params={"maks": MAKS_REKOMENDASI_PER_RUN})
    df["tanggal_kadaluwarsa"] = pd.to_datetime(df["tanggal_kadaluwarsa"])
    return df


def ambil_demand_per_obat_gudang(engine):
    """Ambil total demand 30 hari ke depan per kombinasi obat-gudang,
    sekali query untuk semua kombinasi. Sengaja tidak query di dalam loop
    per batch, supaya tidak jadi N+1 query yang lambat kalau nanti jumlah
    batch berisiko bertambah banyak."""
    query = """
    SELECT obat_id, gudang_id, SUM(prediksi_permintaan) AS total_demand_30_hari
    FROM gold.pred_demand_forecast
    GROUP BY obat_id, gudang_id
    """
    return pd.read_sql(query, engine)


def tentukan_jenis_rekomendasi(baris, demand_per_obat_gudang):
    """Tentukan jenis tindakan berdasarkan angka aktual, BUKAN oleh LLM.

    Logika:
    - Kalau ada gudang lain untuk obat yang sama dengan demand jauh lebih
      tinggi (>= 1.5x demand gudang asal) DAN waktu menuju kadaluwarsa
      masih cukup (> 14 hari untuk proses pemindahan), sarankan redistribusi
      ke gudang dengan demand tertinggi.
    - Kalau waktu menuju kadaluwarsa sudah mepet (<= 14 hari), sarankan
      diskon cepat, karena kemungkinan tidak keburu dipindah.
    - Selain dua kondisi di atas, sarankan prioritas FEFO sebagai langkah
      standar (pastikan batch ini dipakai/dikeluarkan lebih dulu).
    """
    hari_menuju_kadaluwarsa = (baris["tanggal_kadaluwarsa"].date() - date.today()).days

    demand_obat = demand_per_obat_gudang[demand_per_obat_gudang["obat_id"] == baris["obat_id"]]
    demand_gudang_asal_baris = demand_obat[demand_obat["gudang_id"] == baris["gudang_id"]]
    demand_gudang_asal = (
        demand_gudang_asal_baris["total_demand_30_hari"].iloc[0]
        if len(demand_gudang_asal_baris) > 0 else 0.0
    )

    kandidat_tujuan = demand_obat[demand_obat["gudang_id"] != baris["gudang_id"]].copy()
    gudang_tujuan = None
    demand_tujuan = None
    if len(kandidat_tujuan) > 0:
        kandidat_terbaik = kandidat_tujuan.sort_values("total_demand_30_hari", ascending=False).iloc[0]
        ambang_demand = max(demand_gudang_asal, 1e-6) * FAKTOR_DEMAND_LEBIH_TINGGI
        if kandidat_terbaik["total_demand_30_hari"] >= ambang_demand:
            gudang_tujuan = kandidat_terbaik["gudang_id"]
            demand_tujuan = kandidat_terbaik["total_demand_30_hari"]

    if gudang_tujuan is not None and hari_menuju_kadaluwarsa > AMBANG_HARI_MEPET:
        jenis = "redistribusi"
    elif hari_menuju_kadaluwarsa <= AMBANG_HARI_MEPET:
        jenis = "diskon_cepat"
    else:
        jenis = "prioritas_fefo"

    return {
        "jenis_rekomendasi": jenis,
        "hari_menuju_kadaluwarsa": hari_menuju_kadaluwarsa,
        "demand_gudang_asal_30_hari": round(float(demand_gudang_asal), 1),
        "gudang_tujuan": gudang_tujuan,
        "demand_gudang_tujuan_30_hari": round(float(demand_tujuan), 1) if demand_tujuan is not None else None,
    }


def susun_prompt(baris, keputusan):
    """Susun prompt yang menyisipkan angka aktual secara eksplisit,
    supaya LLM tidak punya alasan untuk mengarang angka sendiri."""
    konteks = [
        f"Obat: {baris['nama_generik']} (kode {baris['obat_kode']})",
        f"Batch: {baris['batch_id']}",
        f"Gudang saat ini: {baris['nama_gudang']} ({baris['gudang_id']})",
        f"Sisa stok batch ini: {int(baris['sisa_stok'])} unit",
        f"Hari menuju kadaluwarsa: {keputusan['hari_menuju_kadaluwarsa']} hari",
        f"Probabilitas risiko waste (model klasifikasi): {baris['probabilitas_risiko']:.0%}",
        f"Perkiraan demand 30 hari ke depan di gudang ini: {keputusan['demand_gudang_asal_30_hari']} unit",
        f"Jenis tindakan yang sudah ditentukan: {keputusan['jenis_rekomendasi']}",
    ]
    if keputusan["jenis_rekomendasi"] == "redistribusi":
        konteks.append(
            f"Gudang tujuan redistribusi: {keputusan['gudang_tujuan']} "
            f"(perkiraan demand 30 hari ke depan {keputusan['demand_gudang_tujuan_30_hari']} unit)"
        )

    return (
        "Buat narasi rekomendasi procurement dari data berikut:\n"
        + "\n".join(f"- {baris_konteks}" for baris_konteks in konteks)
    )


def panggil_llm(client, prompt):
    """Panggil Gemini API, kembalikan teks narasinya.

    Catatan: parameter temperature/top_p/top_k sengaja tidak diset, karena
    sudah dinyatakan deprecated oleh Google per rilis Gemini 3.6 Flash,
    cukup andalkan default model.
    """
    response = client.models.generate_content(
        model=NAMA_MODEL_GEMINI,
        contents=prompt,
        config=types.GenerateContentConfig(
            system_instruction=SYSTEM_INSTRUCTION,
        ),
    )
    return response.text.strip()


def ambil_jeda_retry(exception, default_detik=20):
    """Google sebenarnya sudah menyarankan berapa detik harus menunggu
    lewat field retryDelay di isi error 429 (lihat contoh error yang
    ditemukan user, ada 'retryDelay': '2s'). Fungsi ini coba baca angka
    itu supaya jeda retry kita presisi, bukan asal tebak. Kalau strukturnya
    ternyata beda/tidak ketemu, pakai default_detik sebagai jaga-jaga."""
    try:
        detail_list = exception.details.get("error", {}).get("details", [])
        for item in detail_list:
            if item.get("@type", "").endswith("RetryInfo"):
                detik = float(item.get("retryDelay", "").rstrip("s"))
                return detik + 2  # buffer kecil supaya tidak pas mepet
    except (AttributeError, ValueError, TypeError):
        pass
    return default_detik


def panggil_llm_dengan_retry(client, prompt, batch_id):
    """Bungkus panggil_llm dengan retry otomatis kalau kena rate limit
    (429). Error selain rate limit langsung dilempar lagi, tidak perlu
    diulang karena kemungkinan besar bukan soal timing."""
    for percobaan in range(1, MAKS_PERCOBAAN_ULANG + 1):
        try:
            return panggil_llm(client, prompt)
        except errors.ClientError as e:
            kena_rate_limit = e.code == 429
            if kena_rate_limit and percobaan < MAKS_PERCOBAAN_ULANG:
                jeda = ambil_jeda_retry(e)
                print(
                    f"  Batch {batch_id} kena rate limit, percobaan "
                    f"{percobaan}/{MAKS_PERCOBAAN_ULANG}, menunggu {jeda:.0f} detik..."
                )
                time.sleep(jeda)
                continue
            raise


def tulis_ke_gold(daftar_rekomendasi, engine):
    """Tulis hasil ke gold.agent_recommendations, APPEND (bukan truncate),
    karena tabel ini adalah audit trail riwayat rekomendasi dari waktu ke
    waktu, beda karakter dengan pred_demand_forecast/pred_expiry_risk yang
    snapshot kondisi terkini."""
    with engine.begin() as koneksi:
        for rekom in daftar_rekomendasi:
            koneksi.execute(
                text("""
                    INSERT INTO gold.agent_recommendations
                        (obat_id, gudang_id, jenis_rekomendasi, narasi, data_pendukung)
                    VALUES (:obat_id, :gudang_id, :jenis_rekomendasi, :narasi, CAST(:data_pendukung AS JSONB))
                """),
                {
                    "obat_id": rekom["obat_id"],
                    "gudang_id": rekom["gudang_id"],
                    "jenis_rekomendasi": rekom["jenis_rekomendasi"],
                    "narasi": rekom["narasi"],
                    "data_pendukung": json.dumps(rekom["data_pendukung"]),
                },
            )
    print(f"Berhasil menulis {len(daftar_rekomendasi)} baris ke gold.agent_recommendations")


def main():
    engine = buat_koneksi_database()
    client = buat_klien_gemini()

    print("Mengambil batch dengan kategori risiko Tinggi...")
    batch_berisiko = ambil_batch_berisiko_tinggi(engine)
    print(f"Jumlah batch yang diproses: {len(batch_berisiko)}")

    if len(batch_berisiko) == 0:
        print("Tidak ada batch berisiko Tinggi saat ini, tidak ada rekomendasi yang perlu dibuat")
        return

    demand_per_obat_gudang = ambil_demand_per_obat_gudang(engine)

    print(
        f"Memproses {len(batch_berisiko)} batch dengan jeda "
        f"{JEDA_ANTAR_PANGGILAN_DETIK} detik antar panggilan LLM "
        f"(kira-kira {len(batch_berisiko) * JEDA_ANTAR_PANGGILAN_DETIK // 60} menit total)..."
    )

    daftar_rekomendasi = []
    for i, (_, baris) in enumerate(batch_berisiko.iterrows()):
        if i > 0:
            time.sleep(JEDA_ANTAR_PANGGILAN_DETIK)

        keputusan = tentukan_jenis_rekomendasi(baris, demand_per_obat_gudang)
        prompt = susun_prompt(baris, keputusan)

        try:
            narasi = panggil_llm_dengan_retry(client, prompt, baris["batch_id"])
        except Exception as e:
            print(f"Gagal memanggil LLM untuk batch {baris['batch_id']}: {e}")
            continue

        print(f"  [{i + 1}/{len(batch_berisiko)}] {baris['batch_id']} selesai ({keputusan['jenis_rekomendasi']})")

        data_pendukung = {
            "batch_id": baris["batch_id"],
            "sisa_stok": int(baris["sisa_stok"]),
            "probabilitas_risiko": round(float(baris["probabilitas_risiko"]), 4),
            "tanggal_kadaluwarsa": baris["tanggal_kadaluwarsa"].strftime("%Y-%m-%d"),
            **keputusan,
        }

        daftar_rekomendasi.append({
            "obat_id": baris["obat_id"],
            "gudang_id": baris["gudang_id"],
            "jenis_rekomendasi": keputusan["jenis_rekomendasi"],
            "narasi": narasi,
            "data_pendukung": data_pendukung,
        })

    if len(daftar_rekomendasi) == 0:
        print("Tidak ada rekomendasi yang berhasil dibuat (semua panggilan LLM gagal)")
        return

    print("\nDistribusi jenis rekomendasi yang dihasilkan:")
    print(pd.Series([r["jenis_rekomendasi"] for r in daftar_rekomendasi]).value_counts().to_dict())

    tulis_ke_gold(daftar_rekomendasi, engine)


if __name__ == "__main__":
    main()
