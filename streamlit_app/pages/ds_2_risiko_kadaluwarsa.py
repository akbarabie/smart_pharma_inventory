import plotly.express as px
import streamlit as st

from db import ambil_daftar_gudang, ambil_risiko_kadaluwarsa_lengkap
from style import TEMPLATE_PLOTLY, WARNA_RISIKO

st.title("🧪 Klasifikasi Risiko Kadaluwarsa")
st.caption(
    "Distribusi skor probabilitas risiko waste dari model Logistic "
    "Regression, untuk batch yang masih berjalan (belum lewat tanggal "
    "kadaluwarsa)."
)

daftar_gudang = ambil_daftar_gudang()
opsi_gudang = ["Semua Gudang"] + daftar_gudang["nama"].tolist()
gudang_terpilih = st.selectbox("Filter gudang", opsi_gudang)

risiko_df = ambil_risiko_kadaluwarsa_lengkap()
risiko_df = risiko_df[risiko_df["sisa_stok"] > 0]

if gudang_terpilih != "Semua Gudang":
    gudang_id = daftar_gudang[daftar_gudang["nama"] == gudang_terpilih]["gudang_id"].iloc[0]
    risiko_df = risiko_df[risiko_df["gudang_id"] == gudang_id]

kol1, kol2, kol3 = st.columns(3)
kol1.metric("Risiko Tinggi", int((risiko_df["kategori_risiko"] == "Tinggi").sum()))
kol2.metric("Risiko Sedang", int((risiko_df["kategori_risiko"] == "Sedang").sum()))
kol3.metric("Risiko Rendah", int((risiko_df["kategori_risiko"] == "Rendah").sum()))

if len(risiko_df) == 0:
    st.info("Tidak ada batch berjalan untuk filter ini.")
    st.stop()

kol_kiri, kol_kanan = st.columns([2, 1])
with kol_kiri:
    fig_histogram = px.histogram(
        risiko_df, x="probabilitas_risiko", color="kategori_risiko",
        color_discrete_map=WARNA_RISIKO, nbins=30, template=TEMPLATE_PLOTLY,
        labels={"probabilitas_risiko": "Probabilitas Risiko", "kategori_risiko": "Kategori"},
    )
    fig_histogram.update_layout(height=400, title="Distribusi Skor Probabilitas", margin=dict(t=40))
    st.plotly_chart(fig_histogram, width='stretch')

with kol_kanan:
    hitung_kategori = risiko_df["kategori_risiko"].value_counts().reset_index()
    hitung_kategori.columns = ["kategori_risiko", "jumlah"]
    fig_pie = px.pie(
        hitung_kategori, names="kategori_risiko", values="jumlah",
        color="kategori_risiko", color_discrete_map=WARNA_RISIKO, template=TEMPLATE_PLOTLY, hole=0.5,
    )
    fig_pie.update_layout(height=400, title="Proporsi Kategori", margin=dict(t=40))
    st.plotly_chart(fig_pie, width='stretch')

st.divider()
st.subheader("Batch dengan Probabilitas Risiko Tertinggi")
jumlah_n = st.slider("Jumlah batch yang ditampilkan", min_value=5, max_value=50, value=20, step=5)
tabel = risiko_df.sort_values("probabilitas_risiko", ascending=False).head(jumlah_n)[
    ["nama_generik", "nama_gudang", "batch_id", "sisa_stok", "tanggal_kadaluwarsa", "probabilitas_risiko", "kategori_risiko"]
]
st.dataframe(tabel, width='stretch', hide_index=True)

st.divider()
st.subheader("Catatan Evaluasi Model")
kol1, kol2 = st.columns(2)
kol1.metric("ROC-AUC Model Final (Logistic Regression)", "0.557")
kol2.metric("ROC-AUC Baseline (tebak acak)", "0.500")
st.caption(
    "Model ini memang lemah (AUC mendekati acak). Fitur turunan lain "
    "(margin hari, posisi antrean FEFO) dan model berbasis pohon (XGBoost, "
    "LightGBM) sudah dicoba dan tidak membantu, dilaporkan sebagai "
    "keterbatasan model prediksi. Kemungkinan besar outcome "
    "waste di data simulasi ini didominasi variasi acak konsumsi harian, "
    "bukan pola batch yang bisa dipelajari."
)
