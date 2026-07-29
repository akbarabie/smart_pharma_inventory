"""
Script training model forecasting demand per kombinasi obat-gudang.

Alur kerja:
1. Ambil data pergerakan stok dari gold layer, agregasi ke demand harian
2. Evaluasi model (Prophet) dibanding baseline seasonal naive lag-7,
   pakai split berbasis waktu (60 hari terakhir jadi test)
3. Pastikan gold.dim_waktu mencakup tanggal masa depan yang dibutuhkan
4. Fit ulang Prophet pakai SELURUH histori, forecast 30 hari ke depan
5. Tulis hasil forecast (beserta interval bawah/atas) ke
   gold.pred_demand_forecast

Kenapa fit per kombinasi obat-gudang terpisah (80 model), bukan satu
model global: tiap kombinasi punya pola konsumsi dan skala volume yang
beda jauh (obat volume tinggi seperti parasetamol vs obat volume rendah
seperti insulin), model terpisah lebih sederhana dan hasilnya terbukti
lebih baik di evaluasi dibanding baseline. Retrain penuh cuma makan
waktu sekitar 20-30 detik, jadi tidak perlu disimpan satu-satu ke disk,
cukup diandalkan dari script ini setiap kali dijalankan.
"""

import logging
import warnings
from datetime import datetime, timezone

import numpy as np
import pandas as pd
from prophet import Prophet
from sqlalchemy import text

warnings.filterwarnings("ignore")
logging.getLogger("cmdstanpy").setLevel(logging.WARNING)
logging.getLogger("prophet").setLevel(logging.WARNING)

from common import ambil_data_pergerakan, buat_koneksi_database, hitung_demand_harian_lengkap

HARI_TEST = 60
HARI_FORECAST_KE_DEPAN = 30  # kira-kira di tengah siklus kedatangan batch (20-40 hari)

NAMA_HARI_INDONESIA = {
    "Monday": "Senin", "Tuesday": "Selasa", "Wednesday": "Rabu",
    "Thursday": "Kamis", "Friday": "Jumat", "Saturday": "Sabtu", "Sunday": "Minggu",
}


def hitung_mape_mae(aktual, prediksi):
    """MAPE cuma dihitung di hari dengan demand aktual > 0, karena
    pembagian nol bikin metrik ini tidak terdefinisi. MAE disertakan
    sebagai pendamping karena MAPE rapuh untuk obat volume rendah."""
    mask_valid = aktual > 0
    mape = (np.abs((aktual[mask_valid] - prediksi[mask_valid]) / aktual[mask_valid])).mean() * 100
    mae = np.abs(aktual - prediksi).mean()
    return mape, mae


def bangun_model_prophet():
    """yearly_seasonality dimatikan karena data cuma sekitar 2 tahun,
    tidak cukup untuk percaya pola tahunan. weekly_seasonality dinyalakan
    karena data memang didesain turun di akhir pekan."""
    return Prophet(yearly_seasonality=False, weekly_seasonality=True, daily_seasonality=False)


def split_train_test(demand_harian_lengkap):
    """Split berbasis waktu, BUKAN acak, supaya model tidak mengintip
    masa depan saat evaluasi."""
    tanggal_batas = demand_harian_lengkap["tanggal"].max() - pd.Timedelta(days=HARI_TEST)
    data_train = demand_harian_lengkap[demand_harian_lengkap["tanggal"] <= tanggal_batas].copy()
    data_test = demand_harian_lengkap[demand_harian_lengkap["tanggal"] > tanggal_batas].copy()
    return data_train, data_test, tanggal_batas


def evaluasi_baseline_dan_prophet(demand_harian_lengkap, data_test, tanggal_batas):
    """Bandingkan baseline seasonal naive lag-7 dengan Prophet, sebagai
    sanity check sebelum model dipakai untuk forecast produksi."""
    hasil_baseline = []
    hasil_prophet = []

    for (obat_id, gudang_id), grup_test in data_test.groupby(["obat_id", "gudang_id"]):
        grup_lengkap_seri = demand_harian_lengkap[
            (demand_harian_lengkap["obat_id"] == obat_id)
            & (demand_harian_lengkap["gudang_id"] == gudang_id)
        ].sort_values("tanggal").reset_index(drop=True)

        grup_train = grup_lengkap_seri[grup_lengkap_seri["tanggal"] <= tanggal_batas]
        aktual_test = grup_test.sort_values("tanggal")["jumlah_keluar"].values

        # baseline: tebak sama dengan demand di hari yang sama, seminggu lalu
        prediksi_lag7 = grup_lengkap_seri.set_index("tanggal")["jumlah_keluar"].shift(7)
        prediksi_baseline = prediksi_lag7.reindex(grup_test.sort_values("tanggal")["tanggal"]).values
        mape_b, mae_b = hitung_mape_mae(aktual_test, prediksi_baseline)
        hasil_baseline.append({"obat_id": obat_id, "gudang_id": gudang_id, "mape": mape_b, "mae": mae_b})

        # Prophet, fit cuma pakai data train
        df_prophet = grup_train.rename(columns={"tanggal": "ds", "jumlah_keluar": "y"})[["ds", "y"]]
        model = bangun_model_prophet()
        model.fit(df_prophet)

        future = model.make_future_dataframe(periods=HARI_TEST, freq="D")
        forecast = model.predict(future)
        prediksi_prophet = forecast.set_index("ds").loc[grup_test["tanggal"], "yhat"].values
        prediksi_prophet = np.clip(prediksi_prophet, 0, None)
        mape_p, mae_p = hitung_mape_mae(aktual_test, prediksi_prophet)
        hasil_prophet.append({"obat_id": obat_id, "gudang_id": gudang_id, "mape": mape_p, "mae": mae_p})

    ringkasan_baseline = pd.DataFrame(hasil_baseline)
    ringkasan_prophet = pd.DataFrame(hasil_prophet)

    perbandingan = ringkasan_baseline.merge(
        ringkasan_prophet, on=["obat_id", "gudang_id"], suffixes=("_baseline", "_prophet")
    )
    jumlah_membaik = (perbandingan["mape_baseline"] > perbandingan["mape_prophet"]).sum()

    print("Evaluasi model (sanity check sebelum forecast produksi):")
    print(f"  MAPE baseline (seasonal naive lag-7): {ringkasan_baseline['mape'].mean():.2f}%")
    print(f"  MAPE Prophet                        : {ringkasan_prophet['mape'].mean():.2f}%")
    print(f"  MAE baseline : {ringkasan_baseline['mae'].mean():.2f}")
    print(f"  MAE Prophet  : {ringkasan_prophet['mae'].mean():.2f}")
    print(f"  Prophet membaik di {jumlah_membaik} dari {len(perbandingan)} kombinasi obat-gudang")


def pastikan_dim_waktu_masa_depan(engine, tanggal_terakhir):
    """Cek apakah gold.dim_waktu sudah mencakup tanggal masa depan yang
    dibutuhkan untuk forecast, kalau belum generate dan insert barisnya."""
    tanggal_masa_depan = pd.date_range(
        tanggal_terakhir + pd.Timedelta(days=1), periods=HARI_FORECAST_KE_DEPAN, freq="D"
    )

    dim_waktu_ada = pd.read_sql("SELECT tanggal_id, tanggal FROM gold.dim_waktu", engine)
    dim_waktu_ada["tanggal"] = pd.to_datetime(dim_waktu_ada["tanggal"])

    tanggal_belum_ada = tanggal_masa_depan[~tanggal_masa_depan.isin(dim_waktu_ada["tanggal"])]

    if len(tanggal_belum_ada) > 0:
        dim_waktu_baru = pd.DataFrame({"tanggal": tanggal_belum_ada})
        dim_waktu_baru["tanggal_id"] = dim_waktu_baru["tanggal"].dt.strftime("%Y%m%d").astype(int)
        dim_waktu_baru["hari"] = dim_waktu_baru["tanggal"].dt.day_name().map(NAMA_HARI_INDONESIA)
        dim_waktu_baru["bulan"] = dim_waktu_baru["tanggal"].dt.month
        dim_waktu_baru["tahun"] = dim_waktu_baru["tanggal"].dt.year
        dim_waktu_baru["is_weekend"] = dim_waktu_baru["tanggal"].dt.dayofweek.isin([5, 6])
        dim_waktu_baru = dim_waktu_baru[["tanggal_id", "tanggal", "hari", "bulan", "tahun", "is_weekend"]]

        dim_waktu_baru.to_sql("dim_waktu", engine, schema="gold", if_exists="append", index=False)
        print(f"Menambahkan {len(dim_waktu_baru)} baris baru ke gold.dim_waktu")
    else:
        print("Semua tanggal masa depan sudah tersedia di gold.dim_waktu")

    dim_waktu_lengkap = pd.read_sql("SELECT tanggal_id, tanggal FROM gold.dim_waktu", engine)
    dim_waktu_lengkap["tanggal"] = pd.to_datetime(dim_waktu_lengkap["tanggal"])
    return dim_waktu_lengkap


def latih_dan_forecast_produksi(demand_harian_lengkap, tanggal_terakhir):
    """Fit ulang Prophet pakai SELURUH histori (bukan cuma sampai batas
    evaluasi), lalu forecast maju ke depan. Ini model yang benar-benar
    dipakai untuk procurement, beda tujuan dari model evaluasi di atas
    yang sengaja menyisakan data untuk dites."""
    hasil_forecast = []

    for (obat_id, gudang_id), grup in demand_harian_lengkap.groupby(["obat_id", "gudang_id"]):
        grup = grup.sort_values("tanggal")
        df_prophet = grup.rename(columns={"tanggal": "ds", "jumlah_keluar": "y"})[["ds", "y"]]

        model = bangun_model_prophet()
        model.fit(df_prophet)

        future = model.make_future_dataframe(periods=HARI_FORECAST_KE_DEPAN, freq="D")
        forecast = model.predict(future)

        forecast_masa_depan = forecast[forecast["ds"] > tanggal_terakhir].copy()
        # demand dan interval tidak mungkin negatif
        for kolom in ["yhat", "yhat_lower", "yhat_upper"]:
            forecast_masa_depan[kolom] = np.clip(forecast_masa_depan[kolom], 0, None)

        hasil_forecast.append(pd.DataFrame({
            "obat_id": obat_id,
            "gudang_id": gudang_id,
            "tanggal": forecast_masa_depan["ds"].values,
            "prediksi_permintaan": forecast_masa_depan["yhat"].values,
            "prediksi_permintaan_bawah": forecast_masa_depan["yhat_lower"].values,
            "prediksi_permintaan_atas": forecast_masa_depan["yhat_upper"].values,
        }))

    forecast_produksi = pd.concat(hasil_forecast, ignore_index=True)
    print(f"Total baris forecast masa depan: {len(forecast_produksi)}")
    return forecast_produksi


def tulis_ke_gold(forecast_produksi, dim_waktu_lengkap, engine):
    """Gabungkan tanggal_id lalu tulis ke gold.pred_demand_forecast,
    truncate dulu supaya idempotent."""
    forecast_produksi = forecast_produksi.merge(dim_waktu_lengkap, on="tanggal", how="left")

    jumlah_gagal_mapping = forecast_produksi["tanggal_id"].isnull().sum()
    if jumlah_gagal_mapping > 0:
        raise RuntimeError(
            f"Ada {jumlah_gagal_mapping} baris gagal mapping tanggal_id, "
            "cek dulu isi gold.dim_waktu sebelum menulis ke gold"
        )

    hasil = forecast_produksi[[
        "obat_id", "gudang_id", "tanggal_id",
        "prediksi_permintaan", "prediksi_permintaan_bawah", "prediksi_permintaan_atas",
    ]].copy()
    hasil["dibuat_pada"] = datetime.now(timezone.utc)

    with engine.begin() as koneksi:
        koneksi.execute(text("TRUNCATE TABLE gold.pred_demand_forecast"))

    hasil.to_sql("pred_demand_forecast", engine, schema="gold", if_exists="append", index=False)
    print(f"Berhasil menulis {len(hasil)} baris ke gold.pred_demand_forecast")


def main():
    engine = buat_koneksi_database()

    print("Mengambil data pergerakan stok...")
    df = ambil_data_pergerakan(engine)

    print("Menghitung demand harian lengkap...")
    demand_harian_lengkap = hitung_demand_harian_lengkap(df)
    print(f"Jumlah kombinasi obat-gudang: {demand_harian_lengkap.groupby(['obat_id', 'gudang_id']).ngroups}")

    data_train, data_test, tanggal_batas = split_train_test(demand_harian_lengkap)
    print(f"Tanggal batas split train/test: {tanggal_batas.date()}")

    evaluasi_baseline_dan_prophet(demand_harian_lengkap, data_test, tanggal_batas)

    tanggal_terakhir = demand_harian_lengkap["tanggal"].max()
    print("Memastikan gold.dim_waktu mencakup tanggal masa depan...")
    dim_waktu_lengkap = pastikan_dim_waktu_masa_depan(engine, tanggal_terakhir)

    print("Melatih ulang model pakai seluruh histori dan forecast ke depan...")
    forecast_produksi = latih_dan_forecast_produksi(demand_harian_lengkap, tanggal_terakhir)

    tulis_ke_gold(forecast_produksi, dim_waktu_lengkap, engine)


if __name__ == "__main__":
    main()