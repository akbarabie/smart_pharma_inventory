import os
import sys

import streamlit as st

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "agents", "qa_agent"))
from chatbot import buat_sesi_chat, tanya  # noqa: E402

st.title("💬 Tanya Jawab")
st.caption(
    "Chatbot ini cuma bisa menjawab soal stok obat, batch kadaluwarsa, dan "
    "risiko waste di sistem ini, lewat function calling ke 3 fungsi "
    "terbatas (bukan text-to-SQL bebas)."
)

with st.expander("Contoh pertanyaan yang bisa dicoba"):
    st.markdown(
        "- Obat apa saja yang mau kadaluwarsa 30 hari ke depan?\n"
        "- Berapa stok parasetamol di Gudang Jakarta Pusat?\n"
        "- Batch mana saja yang risikonya paling tinggi?"
    )

if "riwayat_chat" not in st.session_state:
    st.session_state.riwayat_chat = []
if "sesi_chat" not in st.session_state:
    try:
        st.session_state.sesi_chat = buat_sesi_chat()
    except Exception as e:
        st.error(f"Gagal menyiapkan chatbot: {e}")
        st.stop()

for pesan in st.session_state.riwayat_chat:
    with st.chat_message(pesan["role"]):
        st.markdown(pesan["content"])

pertanyaan_baru = st.chat_input("Tanya soal stok, kadaluwarsa, atau risiko obat...")
if pertanyaan_baru:
    st.session_state.riwayat_chat.append({"role": "user", "content": pertanyaan_baru})
    with st.chat_message("user"):
        st.markdown(pertanyaan_baru)

    with st.chat_message("assistant"):
        with st.spinner("Mencari jawaban..."):
            try:
                jawaban = tanya(st.session_state.sesi_chat, pertanyaan_baru)
            except Exception as e:
                jawaban = f"Terjadi error saat memproses pertanyaan: {e}"
        st.markdown(jawaban)

    st.session_state.riwayat_chat.append({"role": "assistant", "content": jawaban})
