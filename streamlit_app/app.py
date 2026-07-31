"""
Entry point streamlit_app, Smart Pharma Inventory Intelligence.

File ini berfungsi sebagai router (pola st.navigation), bukan halaman isi.
Dipilih dibanding folder pages/ otomatis biasa, karena st.navigation bisa
mengelompokkan halaman ke judul grup terpisah di sidebar (Data Scientist
vs Data Analyst), sesuatu yang tidak bisa dilakukan folder pages/ otomatis
bawaan Streamlit.
"""

import streamlit as st
from style import css_kustom
from pathlib import Path

st.set_page_config(
    page_title="Smart Pharma Inventory Intelligence",
    page_icon="💊",
    layout="wide",
)
st.markdown(css_kustom(), unsafe_allow_html=True)

# Logo di atas navigasi sidebar
# BASE_DIR = folder streamlit_app/ (tempat app.py berada), sejajar dengan images/
BASE_DIR = Path(__file__).resolve().parent
LOGO_PATH = BASE_DIR / "images" / "logo.png"

if LOGO_PATH.exists():
    st.logo(str(LOGO_PATH), size="large")
else:
    st.sidebar.warning(f"Logo tidak ditemukan: {LOGO_PATH}")

halaman_beranda = st.Page("pages/beranda.py", title="Beranda", icon="🏠", default=True)

halaman_forecast = st.Page("pages/ds_1_forecast_demand.py", title="Forecast Demand", icon="📈")
halaman_risiko = st.Page("pages/ds_2_risiko_kadaluwarsa.py", title="Risiko Kadaluwarsa", icon="🧪")

halaman_dashboard = st.Page("pages/da_1_dashboard.py", title="Dashboard", icon="📊")
halaman_rekomendasi = st.Page("pages/da_2_rekomendasi.py", title="Rekomendasi", icon="💡")
halaman_chatbot = st.Page("pages/da_3_tanya_jawab.py", title="Tanya Jawab", icon="💬")

# Footer — didorong ke bagian bawah sidebar via flexbox
st.sidebar.markdown(
    """
    <style>
    [data-testid="stSidebarUserContent"] {
        display: flex;
        flex-direction: column;
        min-height: calc(100vh - 120px);
    }
    .sidebar-footer {
        margin-top: auto;
        text-align: center;
        padding-top: 16px;
        border-top: 1px solid #BFDBFE;
    }
    .sidebar-footer .footer-team {
        color: #1E40AF;
        font-size: 14px;
        font-weight: 600;
    }
    .sidebar-footer .footer-role {
        color: #3B82F6;
        font-size: 13px;
        margin-top: 2px;
    }
    .sidebar-footer .footer-copyright {
        color: #93C5FD;
        font-size: 11px;
        margin-top: 10px;
        letter-spacing: 0.3px;
    }
    </style>
    <div class="sidebar-footer">
        <div class="footer-team">Akbar, Fikri, Dani</div>
        <div class="footer-role">Data &amp; AI Professional</div>
        <div class="footer-copyright">Copyright &copy; 2026. All rights reserved.</div>
    </div>
    """,
    unsafe_allow_html=True,
)

pg = st.navigation(
    {
        "": [halaman_beranda],
        "Data Scientist": [halaman_forecast, halaman_risiko],
        "Data Analyst": [halaman_dashboard, halaman_rekomendasi, halaman_chatbot],
    }
)

pg.run()