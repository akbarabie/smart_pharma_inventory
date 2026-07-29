"""
Q&A Chatbot lewat Gemini function calling.

Chatbot ini HANYA bisa menjawab lewat 3 fungsi terbatas di tools.py
(get_expiring_batches, get_stock_level, get_top_risk_items), TIDAK ada
text-to-SQL bebas, sesuai keputusan keamanan PRD section 5.2.

SDK google-genai punya fitur "automatic function calling": begitu fungsi
Python biasa (bukan definisi manual JSON schema) dimasukkan ke parameter
tools, SDK otomatis mendeteksi skema fungsi dari type hint dan docstring,
memanggil fungsi yang relevan kalau model memutuskan itu perlu, lalu
mengirim hasilnya balik ke model untuk dirangkai jadi jawaban natural.
Ini menghindari kita menulis loop manual "kalau model minta panggil fungsi
X, jalankan X, kirim hasilnya lagi ke model, ulangi", SDK yang urus.

Chatbot ini SENGAJA dibatasi topiknya cuma soal stok, batch kadaluwarsa,
dan risiko waste di sistem ini, lewat system_instruction di bawah.
Pertanyaan di luar topik itu ditolak, bukan dijawab dari pengetahuan umum
model.
"""

import os

from dotenv import load_dotenv
from google import genai
from google.genai import types

from tools import get_expiring_batches, get_stock_level, get_top_risk_items

NAMA_MODEL_GEMINI = os.getenv("GEMINI_MODEL", "gemini-3.6-flash")

_CLIENT = None


def _dapatkan_client_gemini():
    """Lazy singleton untuk klien Gemini, sama pola-nya seperti _dapatkan_engine()
    di tools.py.

    PENTING, ini bukan sekadar gaya penulisan, tapi perbaikan bug nyata: kalau
    genai.Client() dibuat sebagai variabel lokal biasa di dalam fungsi lalu
    fungsinya selesai, Python langsung menghabisi objek client itu lewat
    garbage collector (refcount jatuh ke nol begitu fungsi selesai), dan
    Client.__del__ di SDK google-genai memanggil close() secara eksplisit saat
    itu terjadi. Chat session yang sudah dibuat masih menyimpan referensi ke
    potongan objek yang sama, tapi koneksi HTTP di baliknya sudah kadung
    ditutup, jadi percobaan pertama send_message() gagal dengan pesan
    "Cannot send a request, as the client has been closed". Menyimpan client
    di variabel modul (bukan lokal fungsi) membuat referensinya tetap hidup
    selama proses berjalan, jadi tidak pernah digarbage-collect di tengah
    jalan.
    """
    global _CLIENT
    if _CLIENT is None:
        load_dotenv()
        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            raise RuntimeError(
                "GEMINI_API_KEY tidak ditemukan di .env, isi dulu sebelum menjalankan chatbot"
            )
        _CLIENT = genai.Client(api_key=api_key)
    return _CLIENT

SYSTEM_INSTRUCTION = """
Kamu adalah asisten tanya-jawab untuk sistem Smart Pharma Inventory
Intelligence, sebuah sistem monitoring stok gudang farmasi. Tugasmu HANYA
menjawab pertanyaan seputar stok obat, batch yang akan kadaluwarsa, dan
tingkat risiko waste, dengan cara memanggil fungsi yang sudah disediakan
(get_expiring_batches, get_stock_level, get_top_risk_items).

Aturan wajib:
- Kamu TIDAK BOLEH menjawab pertanyaan di luar topik gudang obat ini,
  misal soal berita, hitungan matematika umum, coding, atau topik apa pun
  yang tidak berhubungan dengan data yang tersedia lewat fungsi di atas.
  Kalau ditanya di luar topik itu, tolak dengan sopan dan jelaskan bahwa
  kamu cuma bisa membantu soal stok dan risiko kadaluwarsa obat di sistem
  ini.
- Jangan pernah mengarang angka. Semua angka yang kamu sebutkan HARUS
  berasal dari hasil pemanggilan fungsi, bukan dari perkiraanmu sendiri.
- Kalau user tidak menyebut gudang tertentu di pertanyaannya, biarkan
  parameter gudang_id kosong supaya hasilnya mencakup semua gudang, jangan
  mengasumsikan satu gudang tertentu sebagai default.
- Jawab dalam Bahasa Indonesia yang ringkas, natural, dan mudah dipahami
  tim procurement (bukan gaya laporan teknis).
""".strip()


def buat_sesi_chat():
    """Buat sesi chat baru dengan 3 fungsi tool terpasang.

    Satu sesi chat dipakai untuk satu percakapan penuh (bukan dibuat ulang
    di setiap pertanyaan), supaya riwayat tanya-jawab sebelumnya tetap
    diingat model selama sesi berlangsung. Nanti di Streamlit, sesi ini
    disimpan di st.session_state supaya bertahan antar pertanyaan user.
    """
    client = _dapatkan_client_gemini()
    return client.chats.create(
        model=NAMA_MODEL_GEMINI,
        config=types.GenerateContentConfig(
            system_instruction=SYSTEM_INSTRUCTION,
            tools=[get_expiring_batches, get_stock_level, get_top_risk_items],
            temperature=0.2,
        ),
    )


def tanya(sesi_chat, pertanyaan: str) -> str:
    """Kirim satu pertanyaan ke sesi chat yang sudah ada, kembalikan
    jawaban teksnya.

    Pemanggilan fungsi (kalau model memutuskan itu perlu untuk menjawab)
    ditangani otomatis oleh SDK lewat automatic function calling, tidak
    ada loop manual yang perlu ditulis di sini.
    """
    response = sesi_chat.send_message(pertanyaan)
    return response.text.strip()


if __name__ == "__main__":
    # mode CLI sederhana untuk test manual sebelum diwiring ke Streamlit
    print("Q&A chatbot Smart Pharma Inventory (ketik 'keluar' untuk berhenti)")
    sesi = buat_sesi_chat()
    while True:
        pertanyaan = input("\nTanya: ").strip()
        if pertanyaan.lower() in ("keluar", "exit", "quit"):
            break
        try:
            jawaban = tanya(sesi, pertanyaan)
            print(f"Jawab: {jawaban}")
        except Exception as e:
            print(f"Terjadi error: {e}")