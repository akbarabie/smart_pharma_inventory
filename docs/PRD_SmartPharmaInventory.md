# PRD: Smart Pharma Inventory Intelligence
### Sistem Peramalan Stok, Deteksi Risiko Kadaluwarsa, dan AI Procurement Assistant untuk Gudang Obat Vital

**Status:** Draft v1.0
**Durasi pengerjaan:** 7 hari (final project bootcamp, tim 3 orang)
**Role:** Data Engineer, Data Scientist, Data Analyst

---

## 1. Latar Belakang & Problem Statement

Gudang farmasi (rumah sakit, apotek, atau instalasi farmasi daerah) menghadapi dua masalah yang saling bertentangan: kehabisan stok obat vital di satu sisi, dan pemborosan karena obat kadaluwarsa sebelum sempat terpakai di sisi lain. Kedua masalah ini punya akar yang sama, yaitu lemahnya visibilitas terhadap pola konsumsi dan risiko kadaluwarsa per batch, sehingga keputusan pengadaan sering reaktif, bukan berbasis data.

Proyek ini membangun sistem end-to-end yang mengubah data mentah pengadaan dan pergerakan stok menjadi rekomendasi pengadaan yang bisa langsung dipakai tim procurement, dengan lapisan AI agent di atasnya supaya rekomendasi disampaikan dalam bahasa natural, bukan cuma angka di dashboard.

### Tujuan Proyek
- Membangun data pipeline yang mengintegrasikan data resmi (daftar obat esensial dari Fornas) dengan data operasional gudang (stok, batch, kadaluwarsa, dan harga) yang di-localize dari dataset sintetis.
- Membangun model peramalan permintaan per SKU obat dan model klasifikasi risiko kadaluwarsa per batch.
- Membangun dashboard monitoring untuk tim manajemen gudang.
- Membangun AI agent yang menerjemahkan hasil model jadi rekomendasi pengadaan dan menjawab pertanyaan bisnis dalam bahasa natural.

### Target Pengguna
Kepala instalasi farmasi/gudang, tim procurement, manajemen rumah sakit yang perlu ringkasan cepat tanpa membaca tabel mentah.

### Success Metrics (untuk demo/sidang, bukan klaim produksi)
| Metrik | Definisi | Target MVP |
|---|---|---|
| Forecast accuracy | MAPE peramalan permintaan per SKU | dilaporkan apa adanya, dibandingkan baseline naive forecast |
| Precision risiko kadaluwarsa | Precision/recall model klasifikasi batch berisiko kadaluwarsa | dilaporkan apa adanya dengan confusion matrix |
| Potensi waste yang terdeteksi | Nilai rupiah batch berisiko kadaluwarsa yang teridentifikasi lebih awal | dihitung dari data simulasi, dijelaskan sebagai proyeksi |
| Latency AI agent | Waktu respons chatbot Q&A | di bawah 10 detik untuk demo |

Catatan jujur: karena sebagian data bersifat simulasi, metrik bisnis (rupiah waste, service level) harus selalu dilabeli sebagai proyeksi berbasis data simulasi di README dan saat presentasi, bukan diklaim sebagai hasil nyata. Ini justru poin plus kredibilitas saat ditanya penguji.

---

## 2. Arsitektur Data (Bronze - Silver - Gold)

```
                         ┌─────────────────────────────┐
                         │         AIRFLOW DAG          │
                         │  (orkestrasi, jadwal harian) │
                         └──────────────┬───────────────┘
                                        │
        ┌───────────────┬──────────────────────┐
        ▼                ▼                       │
  [Extractor A]     [Extractor B]                 │
  e-Fornas Kemkes   CSV sintetis/Kaggle            │
  (download Excel)  (stok, batch, expiry,          │
                      harga hasil localize)         │
        │                │                        │
        └────────────────┘                        │
                         ▼                          │
                 ┌───────────────┐                  │
                 │  BRONZE (raw)  │  MinIO (S3-compatible)      │
                 │  data mentah   │◄────────────────────────────┘
                 │  apa adanya    │
                 └───────┬────────┘
                         ▼
                 ┌───────────────┐
                 │  Data Quality   │  Great Expectations /
                 │  Validation     │  custom checks
                 └───────┬────────┘
                         ▼
                 ┌───────────────┐
                 │  SILVER         │  Staging schema
                 │  cleaned, typed │  PostgreSQL
                 └───────┬────────┘
                         ▼
                 ┌───────────────┐
                 │  GOLD           │  Star schema
                 │  dimensional    │  PostgreSQL
                 │  model          │
                 └───────┬────────┘
             ┌───────────┼────────────┐
             ▼            ▼            ▼
       [Data Scientist] [Dashboard]        [AI Agent Layer]
       modeling         Streamlit app       Recommendation +
                         (Matplotlib/       Q&A Chatbot
                          Seaborn)
```

### Kenapa bronze-silver-gold, bukan langsung ke satu tabel bersih
Kalau logika transformasi berubah di tengah jalan (dan ini hampir pasti terjadi dalam 7 hari), kalian tidak perlu scraping atau download ulang, tinggal reproses dari bronze. Ini juga memberi jejak audit yang biasa ditanya saat sidang: "kalau datanya salah, dari mana kalian tahu titik kesalahannya".

---

## 3. Sumber Data (Data Lake Bronze Layer)

| Sumber | Jenis | Cara Ambil | Fungsi dalam Model |
|---|---|---|---|
| **e-Fornas Kemenkes** (e-fornas.kemkes.go.id) | Daftar Obat Esensial Nasional, resmi | Download langsung tombol "Unduh Daftar Obat" (Excel), bukan scraping | Dimension table `dim_obat`, flag obat vital/esensial, nama generik, dosis, bentuk sediaan |
| **Dataset sintetis/Kaggle pharmacy inventory (di-localize)** | Data operasional gudang (stok masuk-keluar, batch, tanggal kadaluwarsa) + kolom harga | Download CSV template generik, lalu localize: mapping nama obat ke daftar Fornas, tambah kolom harga dengan asumsi kisaran harga IDR yang wajar | Fact table `fact_stock_movement` dan `fact_procurement_price`, input utama untuk forecasting, klasifikasi risiko kadaluwarsa, dan KPI finansial |
| *(Opsional, konteks saja)* Dataset kelas terapi lokal/impor, Satu Data BPOM | Statistik agregat nasional, resmi | Download manual Excel dari portal | Bukan bagian skema gold, dipakai sebagai satu chart konteks tambahan di Streamlit (ketergantungan impor per kelas terapi), tidak melalui pipeline Airflow |

**Kenapa harga pengadaan tidak lagi diambil dari sumber resmi terpisah:** sudah dicoba dan dicek langsung, e-Katalog LKPP memblokir akses otomatis lewat robots.txt, alternatif data.lkpp.go.id hanya punya data agregat per tahun (bukan per obat), dan pencarian di Kaggle juga tidak menemukan dataset harga obat yang spesifik konteks Indonesia. Detail penelusuran ini dicatat di bagian 11 supaya keputusannya jelas kalau ditanya juri.

**Wajib dicatat di README:** sumber pertama adalah data resmi pemerintah, sumber kedua adalah data simulasi yang di-localize untuk konteks Indonesia (termasuk kolom harga yang berbasis asumsi, bukan harga resmi). Jangan disamarkan seolah semua data real, transparansi ini justru nilai plus profesionalisme.

### Skema Gold (Dimensional Model)
- `fact_stock_movement` (obat_id, gudang_id, tanggal_id, jumlah_masuk, jumlah_keluar, batch_id, tanggal_kadaluwarsa)
- `fact_procurement_price` (obat_id, tanggal_id, harga_referensi, supplier_id) — harga_referensi berasal dari kolom harga hasil localize dataset sintetis, bukan harga resmi pemerintah
- `dim_obat` (obat_id, nama_generik, kategori, flag_vital, bentuk_sediaan)
- `dim_gudang` (gudang_id, nama, wilayah)
- `dim_waktu` (tanggal_id, hari, bulan, tahun, is_weekend)
- `dim_supplier` (supplier_id, nama)
- `pred_demand_forecast` (obat_id, gudang_id, tanggal_id, prediksi_permintaan) — hasil tulis balik dari DS
- `pred_expiry_risk` (batch_id, probabilitas_risiko, kategori_risiko) — hasil tulis balik dari DS

---

## 4. Environment & Tech Stack

| Layer | Tool | Alasan |
|---|---|---|
| Orkestrasi | Apache Airflow (Docker, LocalExecutor) | standar industri, cukup untuk skala 1 minggu |
| Object storage (bronze) | MinIO (Docker, S3-compatible) | gratis, API sama seperti S3 asli, skill yang transferable |
| Data quality | Great Expectations atau custom Python assertion | validasi null, duplikasi, tipe data, format tanggal |
| Warehouse (silver+gold) | PostgreSQL, di-hosting bersama (Supabase/Neon tier gratis), bukan hanya lokal di Docker | relational, familiar, dan yang terpenting bisa diakses bersama oleh DE, DS, dan DA dari laptop masing-masing tanpa harus satu database per orang |
| Modeling | Python: pandas, scikit-learn, statsmodels/Prophet (forecasting), XGBoost/LightGBM (klasifikasi risiko) | interpretable, cepat dilatih dalam waktu terbatas |
| AI Agent | Claude API atau OpenAI API + FastAPI sebagai service wrapper | pola function calling, bukan text-to-SQL bebas |
| Dashboard & visualisasi | Matplotlib dan Seaborn, ditampilkan sebagai halaman/tab di dalam aplikasi Streamlit yang sama dengan chatbot | tidak perlu tool BI terpisah, Data Analyst sudah familiar, interaktivitas dasar (filter gudang/tanggal) ditambah lewat widget Streamlit (selectbox/slider) sebelum plot digambar ulang |
| Chat & dashboard interface | Streamlit (satu aplikasi untuk chatbot Q&A, hasil rekomendasi, dan visualisasi Matplotlib/Seaborn) | cepat dibangun, satu aplikasi untuk dideploy, bukan dua sistem terpisah |
| Container orchestration lokal | Docker Compose | satu perintah untuk menjalankan seluruh stack |
| Version control | Git + GitHub, branch per role, PR review antar anggota | wajib untuk portofolio, tunjukkan commit history yang rapi |

Seluruh stack di atas dijalankan lewat satu `docker-compose.yml` supaya siapa pun di tim (atau reviewer/juri) bisa `docker compose up` dan semuanya jalan tanpa setup manual berjam-jam.

---

## 5. AI Agent Layer

Ini bagian yang membedakan proyek kalian dari final project supply chain generik. Dua kapabilitas, dipisah jelas supaya tidak tumpang tindih dan lebih aman dikerjakan dalam waktu terbatas.

### 5.1 Procurement Recommendation Generator (dimiliki Data Scientist)
Agent terjadwal (dipicu setelah DAG Airflow selesai memperbarui tabel prediksi) yang membaca `pred_demand_forecast` dan `pred_expiry_risk`, menyusun prompt terstruktur berisi angka-angka kunci (SKU, jumlah stok, hari menuju kadaluwarsa, probabilitas risiko), lalu memanggil LLM untuk menghasilkan narasi rekomendasi, misalnya menyarankan redistribusi ke gudang lain, diskon cepat, atau prioritas pemakaian FEFO (first-expired-first-out). Output disimpan sebagai teks di tabel `agent_recommendations` dan ditampilkan di dashboard atau dikirim sebagai ringkasan harian.

Penting: agent ini tidak boleh mengarang angka. Prompt harus secara eksplisit menyisipkan angka dari tabel prediksi sebagai konteks, LLM hanya bertugas merangkai jadi bahasa natural dan memberi saran tindakan, bukan menghitung ulang angkanya sendiri.

### 5.2 Internal Q&A Chatbot (dimiliki Data Analyst)
Chatbot yang menjawab pertanyaan seperti "obat apa saja yang berisiko kadaluwarsa bulan depan". Untuk skala 1 minggu, jangan bangun text-to-SQL bebas, itu berisiko menghasilkan query yang salah atau berbahaya. Sebagai gantinya, pakai pola function calling dengan set tool/fungsi terbatas yang sudah didefinisikan, misalnya `get_expiring_batches(gudang_id, jangka_hari)`, `get_stock_level(obat_id)`, `get_top_risk_items(n)`. LLM hanya memilih fungsi mana yang relevan dari pertanyaan user, lalu fungsi tersebut menjalankan query SQL yang sudah diparameterisasi dan aman, hasilnya dirangkai LLM jadi jawaban natural.

Ini pola yang jauh lebih defensible saat ditanya juri soal keamanan dan reliabilitas dibanding text-to-SQL bebas, dan tetap menunjukkan pemahaman agentic AI yang benar.

---

## 6. Deployment

Airflow, MinIO, dan seluruh proses ETL cukup jalan di Docker Compose lokal di laptop Data Engineer, tidak perlu cloud untuk proses development pipeline itu sendiri.

Yang wajib di-hosting bersama sejak hari pertama adalah database Postgres gold layer-nya, karena ini yang perlu diakses tiga orang dari laptop masing-masing secara bersamaan, bukan cuma oleh DE. Kalau Postgres hanya jalan di dalam Docker Compose lokal milik DE, Data Scientist dan Data Analyst tidak akan pernah bisa connect ke data yang sama, mereka masing-masing akan punya database kosong terpisah. Pakai Postgres gratis yang di-hosting seperti Supabase atau Neon, arahkan DAG Airflow untuk menulis ke sana, lalu bagikan connection string yang sama ke DS dan DA supaya notebook dan aplikasi Streamlit mereka connect ke sumber data yang sama persis.

Untuk demo ke recruiter atau juri, deploy aplikasi Streamlit (berisi chatbot Q&A, tampilan rekomendasi, dan visualisasi Matplotlib/Seaborn) ke Streamlit Community Cloud (gratis), tetap terhubung ke Postgres hosted yang sama. Karena hanya ada satu aplikasi yang perlu dideploy, bukan Streamlit plus tool BI terpisah, ini juga menyederhanakan maintenance selama minggu pengerjaan.

Dengan begini, siapa pun bisa membuka link Streamlit dan mencoba chatbot serta dashboard-nya langsung tanpa harus menjalankan Docker, ini penting untuk nilai jual portofolio karena recruiter jarang mau clone repo dan setup infrastruktur sendiri.

---

## 7. Rencana Kerja 7 Hari

| Hari | Data Engineer | Data Scientist | Data Analyst |
|---|---|---|---|
| 1 | Setup Docker Compose (Airflow, MinIO) + setup Postgres hosted (Supabase/Neon), bagikan connection string ke DS & DA, buat struktur repo dan skema gold di atas kertas, mulai extractor Fornas & CSV sintetis | EDA awal di dataset sintetis, definisikan fitur yang mungkin dipakai, mulai localize nama obat ke daftar Fornas dan tambah kolom harga asumsi | Definisikan KPI dashboard, buat wireframe kasar, setup skeleton aplikasi Streamlit |
| 2 | Selesaikan dua extractor, load ke bronze (MinIO) | Lanjut EDA, feature engineering awal dengan data sample/mock | Siapkan struktur query untuk KPI berdasarkan skema gold yang direncanakan, mulai draft plot Matplotlib/Seaborn dengan data mock |
| 3 | Bangun task validasi kualitas data, transform ke silver | Mulai bangun model forecasting (baseline dulu, lalu tuning) | Bangun halaman visualisasi di Streamlit (Matplotlib/Seaborn) dengan data mock/sample |
| 4 | Bangun transform ke gold (dimensional model), load ke Postgres hosted | Bangun model klasifikasi risiko kadaluwarsa, evaluasi metrik | Sambungkan visualisasi ke data gold asli di Postgres hosted, tambahkan widget filter (gudang/tanggal) |
| 5 | Finalisasi DAG penuh, jadwal otomatis, dokumentasi data dictionary | Tulis prediksi balik ke tabel gold, mulai bangun Recommendation Generator agent | Sambungkan tabel prediksi ke visualisasi, mulai bangun Q&A chatbot (fungsi-fungsi query) |
| 6 | Bantu integrasi end-to-end, testing pipeline penuh | Selesaikan dan uji Recommendation Generator agent | Selesaikan Q&A chatbot, satukan semua halaman (visualisasi + chatbot + rekomendasi) dalam satu aplikasi Streamlit |
| 7 | Freeze pipeline, siapkan demo data, review README bersama | Siapkan narasi teknis model untuk presentasi | Deploy Streamlit demo ke Streamlit Community Cloud, siapkan storytelling bisnis untuk presentasi |

Catatan penting: DE harus memberi kontrak skema gold (nama tabel dan kolom) sejak hari 1, meskipun datanya belum lengkap, supaya DS dan DA bisa mulai kerja paralel dengan data mock/sample tanpa menunggu pipeline selesai. Ini yang paling sering bikin tim bootcamp telat, satu orang jadi bottleneck karena yang lain menunggu.

---

## 8. Risiko & Mitigasi

| Risiko | Mitigasi |
|---|---|
| Data harga hasil localize dianggap kurang meyakinkan | Dokumentasikan basis asumsi harga (kisaran umum obat generik/esensial di Indonesia) secara eksplisit di README, sampaikan sebagai keterbatasan proyek, bukan disembunyikan |
| Timeline 1 minggu terlalu ketat untuk semua fitur | Potong scope nice-to-have lebih dulu: MLflow tracking, text-to-SQL bebas, deployment cloud penuh untuk seluruh stack. MVP wajib: pipeline jalan end-to-end, dua model dengan evaluasi jujur, dashboard dasar, dua agent versi sederhana |
| Dependensi antar role (DA/DS menunggu DE) | Kontrak skema gold ditentukan hari 1, gunakan data dummy/sample sementara pipeline asli belum siap |
| AI agent mengarang angka (hallucination) | Prompt selalu menyisipkan angka aktual dari database sebagai konteks, agent Q&A pakai function calling dengan query terparameterisasi, bukan SQL bebas |
| Data sintetis disalahpahami sebagai data real | Label eksplisit di README dan slide presentasi mana sumber resmi (Fornas) dan mana simulasi/localize (stok, batch, harga) |

---

## 9. Definition of Done (MVP untuk demo hari ke-7)

- Pipeline Airflow berjalan end-to-end dari dua sumber (Fornas + CSV sintetis yang sudah di-localize) sampai tabel gold, bisa dijalankan ulang tanpa duplikasi data.
- Model forecasting dan model klasifikasi risiko kadaluwarsa terlatih, dievaluasi dengan metrik yang jujur dilaporkan (termasuk kalau hasilnya belum bagus).
- Dashboard di dalam aplikasi Streamlit (Matplotlib/Seaborn) menampilkan minimal service level, waste rate proyeksi, dan daftar batch berisiko tinggi.
- Postgres gold layer di-hosting bersama (Supabase/Neon) dan bisa diakses DE, DS, dan DA dari laptop masing-masing dengan connection string yang sama.
- Recommendation Generator menghasilkan minimal satu contoh narasi rekomendasi per hari dari data terbaru.
- Q&A chatbot bisa menjawab minimal tiga jenis pertanyaan bisnis lewat function calling.
- README lengkap: arsitektur, cara menjalankan lewat Docker Compose, sumber data dan status masing-masing (resmi vs simulasi), keterbatasan proyek.

---

## 10. Struktur Repo yang Disarankan

```
smart-pharma-inventory/
├── docker-compose.yml
├── README.md
├── dags/                  # Airflow DAG (Data Engineer)
├── extractors/             # extractor per sumber data
├── data_quality/            # validasi Great Expectations/custom
├── notebooks/               # EDA & eksperimen model (Data Scientist)
├── models/                  # kode training & inference model
├── agents/
│   ├── recommendation_agent/  # Procurement Recommendation Generator
│   └── qa_agent/               # Q&A chatbot function calling
├── streamlit_app/            # satu aplikasi: visualisasi Matplotlib/Seaborn + chatbot + rekomendasi
│   ├── pages/                  # halaman dashboard (per KPI/kategori)
│   └── app.py                  # entry point Streamlit
└── docs/                     # PRD ini, data dictionary, diagram arsitektur
```

---

## 11. Catatan Tambahan (Opsional, Bukan MVP Wajib)

Dua tool berikut sempat dipertimbangkan tapi sengaja tidak masuk MVP, dicatat di sini supaya keputusannya jelas kalau ditanya juri.

**Redis**, sebagai caching layer, bukan pengganti Postgres. Kalau waktu masih ada di hari ke-6 atau ke-7 setelah semua item Definition of Done selesai, bisa ditambahkan untuk dua hal: cache hasil query yang sering diulang di Q&A chatbot, dan cache jawaban LLM untuk pertanyaan yang identik supaya menghemat biaya panggilan API dan mempercepat respons. Ini item bonus, jangan dikerjakan kalau MVP wajib belum selesai.

**Debezium + Kafka**, untuk change data capture (CDC), sengaja tidak dipakai karena tidak ada sumber data di proyek ini yang berupa database operasional live yang terus-menerus ditulis. Ketiga sumber data (Fornas, LKPP, dataset sintetis) sifatnya batch, bukan streaming, jadi CDC tidak punya sesuatu untuk ditangkap. Kebutuhan pembaruan data harian lewat batch Airflow sudah cukup untuk use case pengadaan dan deteksi risiko kadaluwarsa yang tidak butuh latency detik. Dicatat sebagai roadmap produksi: kalau sistem ini nanti terhubung ke database operasional gudang yang live, langkah berikutnya adalah mengganti extractor batch dengan CDC via Debezium untuk mengurangi latency dan beban query ke sistem sumber.

**Sumber harga pengadaan resmi (LKPP/HET), sudah ditelusuri dan sengaja tidak dipakai.** Tiga jalur sempat dicoba: endpoint API e-Katalog LKPP diblokir robots.txt untuk akses otomatis, dataset terbuka data.lkpp.go.id hanya berisi agregat nilai transaksi per tahun (bukan per obat), dan HET Obat Generik dari Kepmenkes hanya tersedia dalam format PDF regulasi yang butuh ekstraksi tabel manual serta cakupannya terbatas ke obat generik saja. Pencarian di Kaggle untuk dataset harga obat Indonesia juga tidak membuahkan hasil, yang ada hanya dataset harga obat India yang tidak relevan secara pasar dan mata uang. Keputusan final: kolom harga memakai asumsi hasil localize di dataset sintetis, didokumentasikan jujur sebagai simulasi di README, bukan diklaim sebagai harga resmi.
