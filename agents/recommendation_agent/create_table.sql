-- Tabel penyimpanan hasil narasi Procurement Recommendation Generator.
-- Sifatnya APPEND-ONLY (bukan truncate+insert seperti pred_demand_forecast
-- dan pred_expiry_risk), karena tabel ini berfungsi sebagai audit trail
-- rekomendasi bisnis dari waktu ke waktu, bukan sekadar snapshot kondisi
-- terkini. Setiap kali agent dijalankan, baris baru ditambahkan, riwayat
-- lama tetap tersimpan.

CREATE TABLE IF NOT EXISTS gold.agent_recommendations (
    rekomendasi_id SERIAL PRIMARY KEY,
    obat_id TEXT NOT NULL,
    gudang_id TEXT NOT NULL,
    jenis_rekomendasi TEXT NOT NULL,
    narasi TEXT NOT NULL,
    data_pendukung JSONB NOT NULL,
    dibuat_pada TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- index untuk mempercepat query "ambil rekomendasi terbaru per obat-gudang",
-- pola akses yang paling sering dipakai nanti oleh Streamlit dan Q&A chatbot
CREATE INDEX IF NOT EXISTS idx_agent_recommendations_obat_gudang
    ON gold.agent_recommendations (obat_id, gudang_id, dibuat_pada DESC);
