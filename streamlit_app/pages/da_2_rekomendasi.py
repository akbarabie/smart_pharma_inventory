import json

import streamlit as st

from db import ambil_daftar_gudang, ambil_rekomendasi
from style import WARNA_REKOMENDASI

st.title("💡 Rekomendasi Procurement")
st.caption(
    "Narasi rekomendasi dari Procurement Recommendation Generator. Jenis "
    "tindakan ditentukan lewat kode program berbasis angka aktual, LLM "
    "cuma bertugas merangkai narasinya."
)

daftar_gudang = ambil_daftar_gudang()
rekomendasi_df = ambil_rekomendasi()

if len(rekomendasi_df) == 0:
    st.info("Belum ada rekomendasi yang dihasilkan. Jalankan agent terlebih dahulu.")
    st.stop()

kol1, kol2, kol3 = st.columns(3)
with kol1:
    opsi_gudang = ["Semua Gudang"] + daftar_gudang["nama"].tolist()
    gudang_terpilih = st.selectbox("Filter gudang", opsi_gudang)
with kol2:
    opsi_jenis = ["Semua Jenis"] + sorted(rekomendasi_df["jenis_rekomendasi"].unique().tolist())
    jenis_terpilih = st.selectbox("Filter jenis rekomendasi", opsi_jenis)
with kol3:
    kata_kunci_obat = st.text_input("Cari nama obat", placeholder="misal: parasetamol")

tampil = rekomendasi_df.copy()
if gudang_terpilih != "Semua Gudang":
    tampil = tampil[tampil["nama_gudang"] == gudang_terpilih]
if jenis_terpilih != "Semua Jenis":
    tampil = tampil[tampil["jenis_rekomendasi"] == jenis_terpilih]
if kata_kunci_obat.strip():
    tampil = tampil[tampil["nama_generik"].str.contains(kata_kunci_obat.strip(), case=False, na=False)]

st.caption(f"Menampilkan {len(tampil)} dari {len(rekomendasi_df)} total rekomendasi (riwayat lengkap, bukan snapshot).")

if len(tampil) == 0:
    st.info("Tidak ada rekomendasi yang cocok dengan filter di atas.")
    st.stop()

st.download_button(
    "Unduh rekomendasi ini sebagai CSV",
    data=tampil[
        ["nama_generik", "nama_gudang", "jenis_rekomendasi", "narasi", "dibuat_pada"]
    ].to_csv(index=False).encode("utf-8"),
    file_name="rekomendasi_procurement.csv",
    mime="text/csv",
)

LABEL_JENIS = {
    "redistribusi": "Redistribusi",
    "diskon_cepat": "Diskon Cepat",
    "prioritas_fefo": "Prioritas FEFO",
}

for _, baris in tampil.iterrows():
    warna = WARNA_REKOMENDASI.get(baris["jenis_rekomendasi"], "#64748B")
    label = LABEL_JENIS.get(baris["jenis_rekomendasi"], baris["jenis_rekomendasi"])
    with st.container(border=True):
        kol_judul, kol_badge = st.columns([4, 1])
        kol_judul.markdown(f"**{baris['nama_generik']}**  •  {baris['nama_gudang']}")
        kol_badge.markdown(
            f"<div style='text-align:right'><span style='background-color:{warna}; "
            f"color:white; padding:3px 10px; border-radius:12px; font-size:0.8em;'>"
            f"{label}</span></div>",
            unsafe_allow_html=True,
        )
        st.write(baris["narasi"])
        with st.expander("Data pendukung (untuk audit)"):
            data_pendukung = baris["data_pendukung"]
            if isinstance(data_pendukung, str):
                data_pendukung = json.loads(data_pendukung)
            st.json(data_pendukung)
        st.caption(f"Dibuat pada {baris['dibuat_pada']}")
