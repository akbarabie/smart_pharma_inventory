# Smart Pharma Inventory Intelligence

Sistem peramalan stok, deteksi risiko kadaluwarsa, dan AI procurement assistant
untuk gudang obat vital. Final project bootcamp data (tim 3 orang: Data Engineer,
Data Scientist, Data Analyst), dikerjakan dalam 7 hari.

> Status: dalam pengerjaan. README ini akan terus diperluas setiap hari
> (arsitektur, cara menjalankan, sumber data, keterbatasan project) sesuai
> Definition of Done di `docs/PRD_SmartPharmaInventory.md`.

## Ringkasan Sumber Data

| Sumber | Status | Catatan |
|---|---|---|
| e-Fornas Kemkes (daftar obat esensial, 663 obat) | Real | Lihat catatan soal cara perolehan di bawah |
| e-Katalog LKPP (harga pengadaan) | **Dihapus dari scope** | Lihat catatan di bawah |
| Data pergerakan stok, batch, dan kadaluwarsa | **Simulasi** | Digenerate sendiri, karena tidak ada dataset publik yang sesuai skema project ini |

### Catatan soal cara perolehan data Fornas

Awalnya extractor Fornas didesain membaca file per-huruf (A-Z) hasil download manual
dari e-fornas.kemkes.go.id, karena situsnya cuma menyediakan unduhan per huruf, bukan
satu file lengkap sekaligus. Setelah sempat mengunduh huruf A (64 dari 663 obat),
ternyata tersedia file referensi lengkap (`Daftar_Obat.csv`, 663 obat) yang disediakan
sebagai bagian dari starter pack bootcamp. Karena file itu berasal dari sumber resmi
yang sama (Formularium Nasional) dan lebih lengkap, extractor diubah untuk membaca
file itu langsung, dibanding memaksa proses manual 26x klik huruf yang hasilnya toh
sama saja. Ini keputusan pragmatis mengutamakan kelengkapan dan efisiensi waktu.

### Catatan soal desain dim_obat (Gold layer)

`dim_obat` dibangun dari seluruh 663 obat Fornas (sumber paling lengkap yang tersedia).
20 obat yang juga dipakai di simulasi stok gudang di-enrich dengan `kategori` dan
`bentuk_sediaan` (informasi ini murni internal, dari desain generator simulasi kita
sendiri, BUKAN dari Fornas, sehingga NULL untuk 643 obat Fornas lainnya yang belum
dipakai di simulasi operasional). `flag_vital` bernilai True untuk semua baris karena
basisnya memang dari daftar obat esensial nasional.

### Catatan soal LKPP dihapus dari scope

PRD awalnya merencanakan e-Katalog LKPP sebagai sumber `fact_procurement_price`, dengan
dua jalur cadangan resmi kalau API bermasalah: halaman unduh manual, dan portal data
terbuka data.lkpp.go.id. Ketiganya sudah dicoba:

- API e-Katalog: ditolak `robots.txt`, tidak dilanjutkan (menghormati aturan situs, bukan
  scraping meskipun secara teknis bisa dipaksakan).
- Halaman unduh manual (e-katalog.lkpp.go.id/unduh): isinya cuma petunjuk penggunaan
  aplikasi (manual PDF), bukan data produk/harga.
- Portal data.lkpp.go.id: isinya statistik agregat kebijakan pengadaan, bukan harga per
  item obat.

Karena ketiga jalur resmi buntu, dan tidak ada satu pun item di Definition of Done yang
bergantung langsung pada `fact_procurement_price` (forecasting pakai `fact_stock_movement`,
dashboard dan recommendation agent bisa jalan tanpa data harga), sumber ini dihapus dari
scope MVP, bukan digantikan data sintetis. Ini keputusan sadar untuk menjaga fokus di
sisa waktu 7 hari, dicatat di sini supaya transparan kalau ditanya saat presentasi.

Detail lengkap dan alasan tiap keputusan arsitektur lainnya ada di `docs/PRD_SmartPharmaInventory.md`.

## Cara Menjalankan (development)

```bash
cp .env.example .env
# isi .env: generate AIRFLOW_FERNET_KEY, isi GOLD_DATABASE_URL dari Neon/Supabase

docker compose up -d --build
```

- Airflow UI: http://localhost:8080 (login: admin / admin)
- MinIO Console: http://localhost:9001 (login sesuai MINIO_ROOT_USER/PASSWORD di .env)

Bagian ini akan dilengkapi terus seiring progres tiap hari.
