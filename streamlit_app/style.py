"""
Palet warna dan styling konsisten untuk seluruh halaman streamlit_app.
Dipakai lintas halaman grup Data Scientist maupun Data Analyst, supaya
visual tidak berantakan atau beda-beda tiap halaman.
"""

WARNA_PRIMER = "#0F766E"
WARNA_AKSEN = "#0891B2"
WARNA_LATAR_KARTU = "#F0FDFA"

WARNA_RISIKO = {
    "Tinggi": "#DC2626",
    "Sedang": "#D97706",
    "Rendah": "#16A34A",
}

WARNA_REKOMENDASI = {
    "redistribusi": "#0891B2",
    "diskon_cepat": "#D97706",
    "prioritas_fefo": "#7C3AED",
}

TEMPLATE_PLOTLY = "plotly_white"


def css_kustom() -> str:
    """CSS tambahan buat mempercantik tampilan default Streamlit, dipanggil
    lewat st.markdown(css_kustom(), unsafe_allow_html=True) di app.py."""
    return f"""
    <style>
    div[data-testid="stMetric"] {{
        background-color: {WARNA_LATAR_KARTU};
        border: 1px solid #99F6E4;
        border-radius: 12px;
        padding: 16px 20px;
    }}
    div[data-testid="stMetric"] label {{
        color: {WARNA_PRIMER};
        font-weight: 600;
    }}
    section[data-testid="stSidebar"] {{
        border-right: 1px solid #E2E8F0;
    }}
    </style>
    """
