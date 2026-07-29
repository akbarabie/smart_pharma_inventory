import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from db import (
    ambil_daftar_gudang,
    ambil_daftar_obat_operasional,
    ambil_fact_stock_movement,
    ambil_pred_demand_forecast,
)
from style import TEMPLATE_PLOTLY, WARNA_AKSEN, WARNA_PRIMER

st.title("📈 Forecast Demand (Prophet)")
st.caption(
    "Perbandingan histori demand aktual dengan hasil forecast 30 hari ke "
    "depan, per kombinasi obat-gudang."
)

daftar_obat = ambil_daftar_obat_operasional()
daftar_gudang = ambil_daftar_gudang()

if len(daftar_obat) == 0:
    st.warning("Belum ada data pergerakan stok untuk obat operasional.")
    st.stop()

kol1, kol2 = st.columns(2)
obat_terpilih = kol1.selectbox("Pilih obat", daftar_obat["nama_generik"], index=0)
gudang_terpilih = kol2.selectbox("Pilih gudang", daftar_gudang["nama"], index=0)

jumlah_hari_histori = st.slider(
    "Jumlah hari histori yang ditampilkan", min_value=30, max_value=365, value=120, step=30
)

obat_id_terpilih = daftar_obat[daftar_obat["nama_generik"] == obat_terpilih]["obat_id"].iloc[0]
gudang_id_terpilih = daftar_gudang[daftar_gudang["nama"] == gudang_terpilih]["gudang_id"].iloc[0]

fact_df = ambil_fact_stock_movement()
forecast_df = ambil_pred_demand_forecast()

histori = (
    fact_df[(fact_df["obat_id"] == obat_id_terpilih) & (fact_df["gudang_id"] == gudang_id_terpilih)]
    .groupby("tanggal")["jumlah_keluar"]
    .sum()
    .reset_index()
    .sort_values("tanggal")
    .tail(jumlah_hari_histori)
)

forecast = forecast_df[
    (forecast_df["obat_id"] == obat_id_terpilih) & (forecast_df["gudang_id"] == gudang_id_terpilih)
].sort_values("tanggal")

fig = go.Figure()
fig.add_trace(
    go.Scatter(
        x=histori["tanggal"], y=histori["jumlah_keluar"], mode="lines",
        name="Demand aktual", line=dict(color=WARNA_PRIMER, width=2),
    )
)
if len(forecast) > 0:
    fig.add_trace(
        go.Scatter(
            x=pd.concat([forecast["tanggal"], forecast["tanggal"][::-1]]),
            y=pd.concat([forecast["prediksi_permintaan_atas"], forecast["prediksi_permintaan_bawah"][::-1]]),
            fill="toself", fillcolor="rgba(8, 145, 178, 0.15)",
            line=dict(color="rgba(255,255,255,0)"), name="Interval prediksi",
        )
    )
    fig.add_trace(
        go.Scatter(
            x=forecast["tanggal"], y=forecast["prediksi_permintaan"], mode="lines",
            name="Forecast", line=dict(color=WARNA_AKSEN, width=2, dash="dash"),
        )
    )
else:
    st.info("Belum ada data forecast untuk kombinasi obat-gudang ini.")

fig.update_layout(
    template=TEMPLATE_PLOTLY, height=450,
    xaxis_title="Tanggal", yaxis_title="Unit",
    legend=dict(orientation="h", yanchor="bottom", y=1.02),
    margin=dict(t=30),
)
st.plotly_chart(fig, width='stretch')

st.divider()
st.subheader("Evaluasi Model (hasil training, bukan dihitung ulang live)")
kol1, kol2, kol3 = st.columns(3)
kol1.metric("MAPE Prophet", "29.21%", delta="-12.64pp vs baseline", delta_color="inverse")
kol2.metric("MAPE Baseline (naive lag-7)", "41.85%")
kol3.metric("Kombinasi Membaik", "79 / 80")
st.caption(
    "Prophet dilatih terpisah per kombinasi obat-gudang (yearly_seasonality "
    "dimatikan karena histori cuma sekitar 2 tahun, weekly_seasonality "
    "dinyalakan karena demand memang didesain turun di akhir pekan). Angka "
    "evaluasi di atas dihitung sekali saat training model, bukan dihitung "
    "ulang secara real time di dashboard ini."
)
