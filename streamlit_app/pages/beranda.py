import streamlit as st
from PIL import Image
from pathlib import Path

from db import ambil_daftar_gudang, ambil_pred_demand_forecast, ambil_risiko_kadaluwarsa_lengkap

st.title("💊 Smart Pharma Inventory Intelligence")
# Menampilkan cover gambar
BASE_DIR = Path(__file__).resolve().parent.parent
img = Image.open(BASE_DIR / "images" / "smart_pharma.png")
st.image(img, use_container_width=True)
st.caption(
    "Sistem peramalan stok, deteksi risiko kadaluwarsa, dan AI procurement "
    "assistant untuk gudang obat vital."
)

st.divider()

risiko_df = ambil_risiko_kadaluwarsa_lengkap()
forecast_df = ambil_pred_demand_forecast()
gudang_df = ambil_daftar_gudang()

kol1, kol2, kol3, kol4 = st.columns(4)
kol1.metric("Gudang Termonitor", len(gudang_df))
kol2.metric("Batch Dipantau", int(risiko_df["batch_id"].nunique()))
kol3.metric("Batch Risiko Tinggi", int((risiko_df["kategori_risiko"] == "Tinggi").sum()))
kol4.metric(
    "Kombinasi Obat-Gudang Diramalkan",
    int(forecast_df.groupby(["obat_id", "gudang_id"]).ngroups) if len(forecast_df) > 0 else 0,
)

st.divider()

kol_kiri, kol_kanan = st.columns(2)
with kol_kiri:
    st.subheader("Data Scientist")
    st.markdown(
        "- **Forecast Demand**, bandingkan hasil prediksi Prophet dengan "
        "histori aktual per kombinasi obat-gudang\n"
        "- **Risiko Kadaluwarsa**, lihat distribusi skor model klasifikasi "
        "dan catatan evaluasinya"
    )
with kol_kanan:
    st.subheader("Procurement (Data Analyst)")
    st.markdown(
        "- **Dashboard**, ringkasan KPI operasional dengan filter gudang "
        "dan rentang tanggal\n"
        "- **Rekomendasi**, narasi tindakan dari Procurement Recommendation "
        "Generator\n"
        "- **Tanya Jawab**, chatbot untuk pertanyaan cepat seputar stok dan "
        "risiko kadaluwarsa"
    )

st.divider()
st.caption(
    "Data pergerakan stok, batch, dan kadaluwarsa bersifat simulasi. Data "
    "obat esensial (Fornas) bersumber resmi dari Kementerian Kesehatan. "
    "Metrik bisnis di seluruh dashboard adalah proyeksi berbasis data "
    "simulasi, bukan klaim hasil nyata."
)
