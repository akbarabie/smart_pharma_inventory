"""
Script training model klasifikasi risiko kadaluwarsa batch obat.

Alur kerja:
1. Ambil data pergerakan stok dari gold layer
2. Turunkan label_risiko dari histori tiap batch (bukan dari data mentah,
   supaya tidak terjadi data leakage, sesuai keputusan di awal project)
3. Rekayasa fitur (shelf_life_hari, rata_rata_demand_obat_gudang,
   rasio_stok_terhadap_demand)
4. Evaluasi model final dengan cross-validation, sebagai sanity check
   sebelum dipakai fit ke seluruh data
5. Fit model final (Logistic Regression) dan scoring ke batch yang masih
   berjalan
6. Tulis hasil scoring ke gold.pred_expiry_risk, simpan model untuk audit

Catatan penting soal performa model: berdasarkan eksplorasi di
notebooks/predik_expired.ipynb, model terbaik yang ditemukan (Logistic
Regression) cuma mencapai ROC-AUC sekitar 0.55, hampir setara tebakan
acak (0.5). Fitur turunan lain (margin_hari, posisi antrean FEFO) sudah
dicoba dan tidak membantu, begitu juga model berbasis pohon (XGBoost,
LightGBM) yang malah overfitting karena data training cuma 168 baris.
Kesimpulannya, outcome waste/habis di data simulasi ini kemungkinan besar
didominasi variasi acak konsumsi harian, bukan pola yang bisa dipelajari.
Ini dilaporkan apa adanya sebagai keterbatasan, bukan disembunyikan.
Script ini TIDAK mengulang proses perbandingan model tersebut, cuma
menjalankan pipeline final yang sudah diputuskan. Detail eksplorasinya
tetap ada di notebook untuk referensi.
"""

import os
import warnings
from datetime import datetime, timezone

import joblib
import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import RepeatedStratifiedKFold, cross_validate
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler
from sqlalchemy import text

warnings.filterwarnings("ignore")

from common import ambil_data_pergerakan, buat_koneksi_database, hitung_demand_harian_lengkap

# fitur final yang dipakai model produksi, sudah melalui proses eliminasi
# di notebook (bulan_terima dan fitur posisi antrean terbukti tidak membantu)
KOLOM_KATEGORIKAL = ["kategori", "gudang_id"]
KOLOM_NUMERIK = [
    "total_masuk",
    "shelf_life_hari",
    "rata_rata_demand_obat_gudang",
    "rasio_stok_terhadap_demand",
]
KOLOM_FITUR = KOLOM_KATEGORIKAL + KOLOM_NUMERIK

PATH_MODEL = os.path.join(os.path.dirname(__file__), "model_expiry_risk_logreg.pkl")


def turunkan_ringkasan_batch(df):
    """Agregasi ke level batch dan turunkan label_risiko dari histori.

    Batch yang tanggal kadaluwarsanya sudah lewat tanggal data terakhir
    dianggap "sudah bisa dilabeli": label 1 kalau masih ada sisa_stok
    (berarti waste), 0 kalau habis terpakai. Batch dengan sisa_stok
    negatif dikeluarkan karena datanya tidak lengkap (kemungkinan ada
    baris "masuk" yang hilang), bukan soal labelnya salah.
    """
    ringkasan_batch = df.groupby(
        ["batch_id", "obat_id", "nama_generik", "gudang_id", "tanggal_kadaluwarsa"]
    ).agg(
        total_masuk=("jumlah_masuk", "sum"),
        total_keluar=("jumlah_keluar", "sum"),
        tanggal_kejadian_pertama=("tanggal", "min"),
    ).reset_index()

    ringkasan_batch["sisa_stok"] = (
        ringkasan_batch["total_masuk"] - ringkasan_batch["total_keluar"]
    )

    tanggal_data_terakhir = df["tanggal"].max()
    ringkasan_batch["sudah_kadaluwarsa"] = (
        ringkasan_batch["tanggal_kadaluwarsa"] <= tanggal_data_terakhir
    )

    batch_training = ringkasan_batch[ringkasan_batch["sudah_kadaluwarsa"]].copy()
    batch_scoring = ringkasan_batch[~ringkasan_batch["sudah_kadaluwarsa"]].copy()

    # keluarkan batch dengan sisa_stok negatif dari kedua kelompok, datanya
    # tidak bisa dipercaya untuk menyimpulkan label maupun untuk fitur
    batch_training = batch_training[batch_training["sisa_stok"] >= 0].copy()
    batch_scoring = batch_scoring[batch_scoring["sisa_stok"] >= 0].copy()

    batch_training["label_risiko"] = (batch_training["sisa_stok"] > 0).astype(int)

    batch_training["kelompok"] = "training"
    batch_scoring["kelompok"] = "scoring"

    print(f"Tanggal data terakhir (dianggap 'hari ini'): {tanggal_data_terakhir.date()}")
    print(f"Batch untuk training : {len(batch_training)}")
    print(f"Batch untuk scoring  : {len(batch_scoring)}")
    print("Distribusi label_risiko training (0 = habis, 1 = ada sisa/waste):")
    print(batch_training["label_risiko"].value_counts().to_dict())

    return pd.concat([batch_training, batch_scoring], ignore_index=True)


def rekayasa_fitur(seluruh_batch, demand_harian_lengkap, df):
    """Tambahkan fitur shelf_life_hari, rata_rata_demand_obat_gudang, dan
    rasio_stok_terhadap_demand ke tiap batch."""
    seluruh_batch["tanggal_terima"] = seluruh_batch["tanggal_kejadian_pertama"]
    seluruh_batch["shelf_life_hari"] = (
        seluruh_batch["tanggal_kadaluwarsa"] - seluruh_batch["tanggal_terima"]
    ).dt.days

    # rata-rata demand harian per kombinasi obat-gudang dari seluruh histori,
    # dipakai sebagai proxy kecepatan konsumsi normal (bukan demand batch itu
    # sendiri). Keterbatasan yang disadari: dihitung dari full histori, bukan
    # cuma sebelum batch diterima, kompromi wajar untuk skala project ini.
    rata_rata_demand = (
        demand_harian_lengkap.groupby(["obat_id", "gudang_id"])["jumlah_keluar"]
        .mean()
        .reset_index()
        .rename(columns={"jumlah_keluar": "rata_rata_demand_obat_gudang"})
    )
    seluruh_batch = seluruh_batch.merge(rata_rata_demand, on=["obat_id", "gudang_id"], how="left")

    kategori_obat = df[["obat_id", "kategori"]].drop_duplicates()
    seluruh_batch = seluruh_batch.merge(kategori_obat, on="obat_id", how="left")

    seluruh_batch["rasio_stok_terhadap_demand"] = np.where(
        seluruh_batch["rata_rata_demand_obat_gudang"] > 0,
        seluruh_batch["total_masuk"] / seluruh_batch["rata_rata_demand_obat_gudang"],
        np.nan,
    )

    jumlah_kosong = seluruh_batch[KOLOM_FITUR].isnull().sum().sum()
    if jumlah_kosong > 0:
        print(f"Peringatan: ada {jumlah_kosong} nilai kosong di kolom fitur, cek lagi sebelum lanjut")

    return seluruh_batch


def bangun_pipeline_model():
    """Pipeline preprocessing + Logistic Regression, ini model produksi
    yang dipilih dari perbandingan di notebook (lihat docstring modul)."""
    preprocessor = ColumnTransformer(
        transformers=[
            ("kategorikal", OneHotEncoder(handle_unknown="ignore"), KOLOM_KATEGORIKAL),
            ("numerik", StandardScaler(), KOLOM_NUMERIK),
        ]
    )
    return Pipeline([
        ("preprocessing", preprocessor),
        ("model", LogisticRegression(max_iter=1000, class_weight="balanced")),
    ])


def evaluasi_model(X, y):
    """Sanity check performa model sebelum dipakai fit ke seluruh data.

    Repeated stratified k-fold dipakai karena data training cuma sekitar
    168 baris, terlalu kecil untuk percaya satu kali split saja.
    """
    cv = RepeatedStratifiedKFold(n_splits=5, n_repeats=5, random_state=42)
    metrik = ["precision", "recall", "f1", "roc_auc"]

    hasil = cross_validate(bangun_pipeline_model(), X, y, cv=cv, scoring=metrik)

    print("Evaluasi model final (repeated stratified 5-fold x 5 repeat):")
    for m in metrik:
        skor = hasil[f"test_{m}"]
        print(f"  {m:10s}: rata-rata {skor.mean():.3f} (std {skor.std():.3f})")

    # ambang 0.65 ini yang sebelumnya disepakati sebagai batas "layak lanjut
    # tuning". pesan dibuat dinamis (bukan teks tetap) supaya kalau nanti
    # datanya berubah dan AUC membaik, log run ini tidak ikut-ikutan bilang
    # "lemah" padahal angkanya sudah tidak lemah lagi
    auc_rata_rata = hasil["test_roc_auc"].mean()
    if auc_rata_rata < 0.65:
        print(
            f"Catatan: AUC run ini ({auc_rata_rata:.3f}) masih di bawah ambang 0.65, "
            "konsisten dengan keterbatasan yang didokumentasikan di notebook eksperimen."
        )
    else:
        print(
            f"Catatan: AUC run ini ({auc_rata_rata:.3f}) sudah di atas ambang 0.65, "
            "ini perubahan dari hasil eksplorasi awal, layak dicek lagi datanya kenapa membaik."
        )


def latih_dan_skor(data_training, data_scoring):
    """Fit model final pakai seluruh data training, lalu scoring ke batch
    yang masih berjalan. Kategori risiko dibagi berdasarkan persentil dari
    distribusi probabilitas hasil scoring sendiri, bukan ambang tetap,
    karena model ini lemah dan skornya cenderung mengumpul di tengah."""
    X_train = data_training[KOLOM_FITUR]
    y_train = data_training["label_risiko"].astype(int)

    model_final = bangun_pipeline_model()
    model_final.fit(X_train, y_train)

    X_scoring = data_scoring[KOLOM_FITUR]
    data_scoring = data_scoring.copy()
    data_scoring["probabilitas_risiko"] = model_final.predict_proba(X_scoring)[:, 1]

    batas_tinggi = data_scoring["probabilitas_risiko"].quantile(0.80)
    batas_sedang = data_scoring["probabilitas_risiko"].quantile(0.50)

    def kategorikan(p):
        if p >= batas_tinggi:
            return "Tinggi"
        elif p >= batas_sedang:
            return "Sedang"
        return "Rendah"

    data_scoring["kategori_risiko"] = data_scoring["probabilitas_risiko"].apply(kategorikan)

    print("Distribusi kategori risiko hasil scoring:")
    print(data_scoring["kategori_risiko"].value_counts().to_dict())

    return model_final, data_scoring


def tulis_ke_gold(data_scoring, engine):
    """Tulis hasil scoring ke gold.pred_expiry_risk, truncate dulu supaya
    idempotent (aman dijalankan berkali-kali tanpa duplikasi)."""
    hasil = data_scoring[["batch_id", "probabilitas_risiko", "kategori_risiko"]].copy()
    hasil["dibuat_pada"] = datetime.now(timezone.utc)

    with engine.begin() as koneksi:
        koneksi.execute(text("TRUNCATE TABLE gold.pred_expiry_risk"))

    hasil.to_sql("pred_expiry_risk", engine, schema="gold", if_exists="append", index=False)
    print(f"Berhasil menulis {len(hasil)} baris ke gold.pred_expiry_risk")


def main():
    engine = buat_koneksi_database()

    print("Mengambil data pergerakan stok...")
    df = ambil_data_pergerakan(engine)

    print("Menghitung demand harian lengkap...")
    demand_harian_lengkap = hitung_demand_harian_lengkap(df)

    print("Menurunkan label risiko dari histori batch...")
    seluruh_batch = turunkan_ringkasan_batch(df)

    print("Menghitung fitur...")
    seluruh_batch = rekayasa_fitur(seluruh_batch, demand_harian_lengkap, df)

    data_training = seluruh_batch[seluruh_batch["kelompok"] == "training"].copy()
    data_scoring = seluruh_batch[seluruh_batch["kelompok"] == "scoring"].copy()

    evaluasi_model(data_training[KOLOM_FITUR], data_training["label_risiko"].astype(int))

    print("Melatih model final dan scoring ke batch yang masih berjalan...")
    model_final, data_scoring = latih_dan_skor(data_training, data_scoring)

    tulis_ke_gold(data_scoring, engine)

    joblib.dump(model_final, PATH_MODEL)
    print(f"Model final disimpan di {PATH_MODEL}")


if __name__ == "__main__":
    main()