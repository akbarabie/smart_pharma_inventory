"""
DAG: extract_to_bronze

Menjalankan dua extractor secara terjadwal harian, menulis hasilnya ke
bronze layer (MinIO):
    1. extract_fornas       -> baca semua file Excel Fornas, gabungkan, upload
    2. generate_synthetic_stock -> generate ulang simulasi stok, upload

Kedua task ini independen satu sama lain (tidak ada dependency di antaranya),
jadi Airflow boleh menjalankan keduanya paralel.
"""

from datetime import datetime, timedelta
 
from airflow import DAG
from airflow.operators.bash import BashOperator
from airflow.operators.empty import EmptyOperator
 
default_args = {
    "owner": "data-engineer",
    "retries": 1,
    "retry_delay": timedelta(minutes=5),
}
 
# Jadwal custom: tiap hari Minggu, jam 23:00 sampai 23:45, tiap 15 menit (4 kali run).
# Format cron: menit jam tanggal bulan hari_minggu
#   */15 -> menit ke 0, 15, 30, 45
#   23   -> jam 23
#   *    -> tiap tanggal
#   *    -> tiap bulan
#   0    -> khusus hari Minggu (konvensi cron: 0 = Minggu)
SCHEDULE_CRON = "*/15 23 * * 0"
 
with DAG(
    dag_id="extract_to_bronze",
    description="Bronze (extract) -> validasi data quality -> Silver -> Gold",
    default_args=default_args,
    schedule=SCHEDULE_CRON,
    start_date=datetime(2026, 7, 25),
    catchup=False,  # PENTING: tanpa ini, Airflow akan mencoba menjalankan ulang
                    # semua run dari start_date sampai hari ini begitu DAG diaktifkan
    tags=["bronze", "extract"],
) as dag:
 
    # Node start/end ini murni untuk kerapian visual graph di Airflow UI,
    # tidak menjalankan logika apa pun (EmptyOperator).
    start = EmptyOperator(task_id="start")
    end = EmptyOperator(task_id="end")
 
    extract_fornas = BashOperator(
        task_id="extract_fornas",
        bash_command="python extractors/extract_fornas.py",
        cwd="/opt/airflow",
    )
 
    generate_synthetic_stock = BashOperator(
        task_id="generate_synthetic_stock",
        bash_command="python extractors/generate_synthetic_stock.py",
        cwd="/opt/airflow",
    )
 
    validate_bronze = BashOperator(
        task_id="validate_bronze",
        bash_command="python data_quality/validate_bronze.py",
        cwd="/opt/airflow",
    )
 
    transform_to_silver = BashOperator(
        task_id="transform_to_silver",
        bash_command="python transform/transform_to_silver.py",
        cwd="/opt/airflow",
    )
 
    transform_to_gold = BashOperator(
        task_id="transform_to_gold",
        bash_command="python transform/transform_to_gold.py",
        cwd="/opt/airflow",
    )
 
    # ---------------------------------------------------------------
    # Task Data Scientist: training dan scoring model, ditulis ke gold
    # ---------------------------------------------------------------
    # penting, sebelum task ini bisa jalan, dependency di
    # requirements/ds.txt (pandas, scikit-learn, prophet, joblib,
    # python-dotenv) wajib sudah ditambahkan ke image Airflow lewat
    # docker/airflow/Dockerfile, kalau belum task ini akan gagal dengan
    # ModuleNotFoundError. lihat catatan review untuk contoh perubahannya.
    train_expiry_risk = BashOperator(
        task_id="train_expiry_risk",
        bash_command="python models/train_expiry_risk.py",
        cwd="/opt/airflow",
    )
    train_demand_forecast = BashOperator(
        task_id="train_demand_forecast",
        bash_command="python models/train_demand_forecast.py",
        cwd="/opt/airflow",
    )
 
    # ---------------------------------------------------------------
    # Task agent: Procurement Recommendation Generator
    # ---------------------------------------------------------------
    # WAJIB jalan SETELAH train_expiry_risk dan train_demand_forecast
    # selesai, karena dia membaca gold.pred_expiry_risk dan
    # gold.pred_demand_forecast, harus data terbaru bukan data basi dari
    # run sebelumnya. Butuh dependency tambahan (google-genai) di
    # requirements/ds.txt, dan GEMINI_API_KEY wajib ada di .env yang sama
    # dipakai container ini.
    generate_recommendations = BashOperator(
        task_id="generate_recommendations",
        bash_command="python agents/recommendation_agent/generate_recommendations.py",
        cwd="/opt/airflow",
    )
 
    # Kedua extractor tetap independen satu sama lain (jalan paralel), tapi
    # keduanya harus selesai dulu sebelum validate_bronze jalan (butuh kedua
    # file mentahnya sudah ada). Kalau validate_bronze gagal (exit code 1),
    # task setelahnya tidak akan dijalankan (Airflow otomatis stop di task
    # yang gagal), jadi data bermasalah tidak akan pernah sampai ke Silver/Gold.
    start >> [extract_fornas, generate_synthetic_stock] >> validate_bronze
    validate_bronze >> transform_to_silver >> transform_to_gold
    transform_to_gold >> [train_expiry_risk, train_demand_forecast]
    [train_expiry_risk, train_demand_forecast] >> generate_recommendations >> end
