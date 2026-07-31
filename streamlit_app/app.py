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

st.set_page_config(
    page_title="Smart Pharma Inventory Intelligence",
    page_icon="💊",
    layout="wide",
)
st.markdown(css_kustom(), unsafe_allow_html=True)

halaman_beranda = st.Page("pages/beranda.py", title="Beranda", icon="🏠", default=True)

halaman_forecast = st.Page("pages/ds_1_forecast_demand.py", title="Forecast Demand", icon="📈")
halaman_risiko = st.Page("pages/ds_2_risiko_kadaluwarsa.py", title="Risiko Kadaluwarsa", icon="🧪")

halaman_dashboard = st.Page("pages/da_1_dashboard.py", title="Dashboard", icon="📊")
halaman_rekomendasi = st.Page("pages/da_2_rekomendasi.py", title="Rekomendasi", icon="💡")
halaman_chatbot = st.Page("pages/da_3_tanya_jawab.py", title="Tanya Jawab", icon="💬")

# Footer
st.sidebar.markdown("---")
st.sidebar.markdown(
    """
    <div style="
        text-align:center;
        color:#9CA3AF;
        font-size:14px;
        padding-top:10px;
        padding-bottom:5px;
    ">
        <strong>Akbar, Fikri, Dani</strong><br>
        Data & AI Professional
    </div>
    """,
    unsafe_allow_html=True
)

pg = st.navigation(
    {
        "": [halaman_beranda],
        "Data Scientist": [halaman_forecast, halaman_risiko],
        "Data Analyst": [halaman_dashboard, halaman_rekomendasi, halaman_chatbot],
    }
)

pg.run()
