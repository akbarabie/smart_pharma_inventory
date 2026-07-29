# Dockerfile untuk image Airflow custom project ini.
# Kenapa bikin Dockerfile sendiri, bukan pakai environment variable
# _PIP_ADDITIONAL_REQUIREMENTS yang ada di contoh resmi Airflow:
# variabel itu memang praktis untuk coba-coba sebentar, tapi menurut
# dokumentasi resminya sendiri "not intended to be used in production"
# karena setiap kali container restart, dependency di-install ulang dari nol,
# jadi lambat dan tidak konsisten. Build image sendiri sekali di awal jauh lebih tepat.

FROM apache/airflow:2.9.3-python3.11

# Salin daftar dependency python yang dibutuhkan task-task di dalam DAG
# (extractor, koneksi ke MinIO, koneksi ke Postgres gold, dan seterusnya)
COPY requirements/airflow.txt /requirements-airflow.txt

# PENTING: install dengan --constraint mengarah ke constraints file RESMI
# Airflow untuk versi 2.9.3 + Python 3.11. Tanpa ini, pip bebas memilih versi
# terbaru untuk tiap package (termasuk dependency yang sebenarnya sudah
# dipakai Airflow sendiri, seperti SQLAlchemy), dan itu bisa diam-diam merusak
# model internal Airflow tanpa ada tanda apa pun sampai container dijalankan.
# Kasus nyata yang kejadian di project ini: pip memasang SQLAlchemy 2.0.31
# padahal Airflow 2.9.3 ditulis dan ditest untuk SQLAlchemy 1.4.52, hasilnya
# airflow-init crash total. Constraint ini mengunci semua dependency supaya
# konsisten dengan kombinasi versi yang sudah resmi ditest Apache Airflow.
ARG AIRFLOW_VERSION=2.9.3
ARG PYTHON_VERSION=3.11
RUN pip install --no-cache-dir -r /requirements-airflow.txt \
    --constraint "https://raw.githubusercontent.com/apache/airflow/constraints-${AIRFLOW_VERSION}/constraints-${PYTHON_VERSION}.txt"

# --- Dependency tambahan untuk sisi Data Scientist ---
# prophet (dipakai di models/train_demand_forecast.py) jalan di atas cmdstan,
# yaitu backend Stan yang di-compile dari source C++. Image dasar Airflow
# tidak menyertakan compiler, jadi harus ditambahkan lebih dulu sebagai root,
# baru kembali ke user airflow untuk pip install (matching praktik resmi
# Airflow, jangan install python package sebagai root).
USER root
RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*
USER airflow

# requirements/ds.txt isinya pandas, scikit-learn, prophet, joblib,
# python-dotenv (lihat file itu untuk daftar lengkapnya). Tetap pakai
# constraint file yang sama supaya package yang overlap dengan Airflow
# (misal sqlalchemy) tidak diam-diam ganti versi.
COPY requirements/ds.txt /requirements-ds.txt
RUN pip install --no-cache-dir -r /requirements-ds.txt \
    --constraint "https://raw.githubusercontent.com/apache/airflow/constraints-${AIRFLOW_VERSION}/constraints-${PYTHON_VERSION}.txt"

# pastikan cmdstan sudah selesai di-compile SAAT BUILD IMAGE, bukan ditunda
# sampai task Airflow pertama kali jalan. kalau ditunda, kompilasi itu bisa
# gagal saat runtime karena container tidak selalu punya akses tulis/jaringan
# yang sama seperti saat proses build image
RUN python -m cmdstanpy.install_cmdstan