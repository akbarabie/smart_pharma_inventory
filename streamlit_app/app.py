"""
Entry point streamlit_app, Smart Pharma Inventory Intelligence.
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

# --- Override tampilan sidebar: background, posisi logo, layout flex ---
# Dipisah dari css_kustom() dan diinjeksi belakangan + pakai !important
# supaya pasti menang di cascade, terlepas dari rule apa pun di style.py.
st.markdown(
    """
    <style>
    /* Background sidebar — biru muda, nuansa tech */
    section[data-testid="stSidebar"] {
        background-color: #EAF2FF !important;
    }

    /* Logo di-tengah-kan secara horizontal, lepas dari flow flex header
       supaya tombol collapse (>>) di kanan atas tidak ikut bergeser */
    [data-testid="stSidebarHeader"] {
        position: relative;
        min-height: 64px;
    }
    [data-testid="stSidebarHeader"] img {
        position: absolute;
        left: 50%;
        top: 50%;
        transform: translate(-50%, -50%);
    }

    /* Jadikan seluruh isi sidebar flex-column agar footer bisa
       didorong ke dasar viewport lewat margin-top: auto */
    section[data-testid="stSidebar"] > div:first-child {
        display: flex;
        flex-direction: column;
        min-height: 100vh;
    }
    [data-testid="stSidebarUserContent"] {
        margin-top: auto;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

# Logo di atas navigasi sidebar
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

# Footer — teks hitam/gelap supaya kontras jelas di atas background biru muda
st.sidebar.markdown(
    """
    <style>
    .sidebar-footer {
        text-align: center;
        padding-top: 16px;
        border-top: 1px solid #BFDBFE;
    }
    .sidebar-footer .footer-team {
        color: #111827;
        font-size: 14px;
        font-weight: 600;
    }
    .sidebar-footer .footer-role {
        color: #1F2937;
        font-size: 13px;
        margin-top: 2px;
    }
    .sidebar-footer .footer-copyright {
        color: #4B5563;
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