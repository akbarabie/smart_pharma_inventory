from datetime import timedelta

import pandas as pd
import plotly.express as px
import streamlit as st

from db import (
    ambil_daftar_gudang,
    ambil_risiko_kadaluwarsa_lengkap,
    hitung_saldo_harian_lengkap,
    hitung_service_level,
    hitung_waste_rate_proyeksi,
)
from style import TEMPLATE_PLOTLY, WARNA_PRIMER, WARNA_RISIKO

st.title("📊 Dashboard Monitoring Gudang")
st.caption("Ringkasan operasional dengan filter gudang dan rentang tanggal.")

daftar_gudang = ambil_daftar_gudang()
saldo_harian_awal = hitung_saldo_harian_lengkap()
tanggal_data_paling_awal = saldo_harian_awal["tanggal"].min().date()
tanggal_data_paling_akhir = saldo_harian_awal["tanggal"].max().date()

kol_filter1, kol_filter2 = st.columns([2, 1])
with kol_filter1:
    gudang_terpilih = st.multiselect(
        "Filter gudang", daftar_gudang["nama"].tolist(), default=daftar_gudang["nama"].tolist()
    )
with kol_filter2:
    rentang_tanggal = st.date_input(
        "Rentang tanggal",
        value=(tanggal_data_paling_akhir - timedelta(days=90), tanggal_data_paling_akhir),
        min_value=tanggal_data_paling_awal,
        max_value=tanggal_data_paling_akhir,
    )

if len(gudang_terpilih) == 0:
    st.warning("Pilih minimal satu gudang untuk melihat data.")
    st.stop()

# st.date_input mengembalikan tuple (mulai, akhir) kalau user sudah pilih
# keduanya, tapi cuma satu tanggal (bukan tuple) selama user baru klik satu
# ujung rentang. Ditangani di sini supaya halaman tidak error di kondisi
# transisi itu, bukan langsung anggap selalu dapat 2 tanggal.
if isinstance(rentang_tanggal, tuple) and len(rentang_tanggal) == 2:
    tanggal_mulai_pilihan, tanggal_akhir_pilihan = rentang_tanggal
else:
    st.info("Pilih tanggal akhir rentang untuk melanjutkan.")
    st.stop()

gudang_id_terpilih = daftar_gudang[daftar_gudang["nama"].isin(gudang_terpilih)]["gudang_id"].tolist()

saldo_harian = saldo_harian_awal
risiko_df = ambil_risiko_kadaluwarsa_lengkap()

tanggal_mulai = pd.Timestamp(tanggal_mulai_pilihan)
tanggal_akhir = pd.Timestamp(tanggal_akhir_pilihan)

service_level = hitung_service_level(saldo_harian, tanggal_mulai, tanggal_akhir, gudang_id_terpilih)
waste_rate = hitung_waste_rate_proyeksi(risiko_df, gudang_id_terpilih)
jumlah_risiko_tinggi = int(
    (
        (risiko_df["kategori_risiko"] == "Tinggi")
        & (risiko_df["gudang_id"].isin(gudang_id_terpilih))
        & (risiko_df["sisa_stok"] > 0)
    ).sum()
)

kol1, kol2, kol3 = st.columns(3)
kol1.metric(
    "Service Level", f"{service_level:.1f}%",
    help="Persentase hari saldo stok masih di atas nol, proxy karena tidak ada data permintaan yang eksplisit ditolak",
)
kol2.metric(
    "Waste Rate Proyeksi", f"{waste_rate:.1f}%",
    help="Persentase unit stok batch berjalan berkategori risiko Tinggi, dalam unit karena data harga di luar scope project",
)
kol3.metric("Batch Risiko Tinggi", jumlah_risiko_tinggi)

st.divider()

kol_kiri, kol_kanan = st.columns(2)
with kol_kiri:
    st.subheader("Komposisi Risiko Stok Berjalan")
    subset_risiko = risiko_df[(risiko_df["sisa_stok"] > 0) & (risiko_df["gudang_id"].isin(gudang_id_terpilih))]
    if len(subset_risiko) > 0:
        ringkasan = subset_risiko.groupby("kategori_risiko")["sisa_stok"].sum().reset_index()
        fig_bar = px.bar(
            ringkasan, x="kategori_risiko", y="sisa_stok", color="kategori_risiko",
            color_discrete_map=WARNA_RISIKO, template=TEMPLATE_PLOTLY,
            labels={"sisa_stok": "Total Sisa Stok (unit)", "kategori_risiko": "Kategori Risiko"},
        )
        fig_bar.update_layout(height=380, showlegend=False, margin=dict(t=30))
        st.plotly_chart(fig_bar, width='stretch')
    else:
        st.info("Tidak ada batch berjalan untuk filter ini.")

with kol_kanan:
    st.subheader("Service Level per Gudang")
    hasil_per_gudang = []
    for _, baris in daftar_gudang[daftar_gudang["gudang_id"].isin(gudang_id_terpilih)].iterrows():
        sl = hitung_service_level(saldo_harian, tanggal_mulai, tanggal_akhir, [baris["gudang_id"]])
        hasil_per_gudang.append({"gudang": baris["nama"], "service_level": sl})
    df_sl_gudang = pd.DataFrame(hasil_per_gudang)
    fig_sl = px.bar(
        df_sl_gudang, x="gudang", y="service_level", template=TEMPLATE_PLOTLY,
        labels={"service_level": "Service Level (%)", "gudang": "Gudang"},
    )
    fig_sl.update_traces(marker_color=WARNA_PRIMER)
    fig_sl.update_layout(height=380, margin=dict(t=30), yaxis_range=[0, 100])
    st.plotly_chart(fig_sl, width='stretch')

st.divider()
st.subheader("Batch dengan Risiko Tertinggi")
tabel = (
    risiko_df[(risiko_df["sisa_stok"] > 0) & (risiko_df["gudang_id"].isin(gudang_id_terpilih))]
    .sort_values("probabilitas_risiko", ascending=False)
    .head(15)[["nama_generik", "nama_gudang", "sisa_stok", "tanggal_kadaluwarsa", "kategori_risiko"]]
)
st.dataframe(tabel, width='stretch', hide_index=True)
st.download_button(
    "Unduh tabel ini sebagai CSV",
    data=tabel.to_csv(index=False).encode("utf-8"),
    file_name="batch_risiko_tertinggi.csv",
    mime="text/csv",
)
