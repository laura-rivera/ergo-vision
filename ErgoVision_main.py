import streamlit as st
from common import build_pose_model, try_limit_opencv_threads
from sidebar_config import render_sidebar
from mode_lateral import render_lateral
from mode_frontal import render_frontal

st.set_page_config(
    page_title="ErgoVision – Postura e Iluminación (Lateral & Frontal)",
    page_icon="🧘",
    layout="wide",
)

try_limit_opencv_threads(2)

@st.cache_resource(show_spinner=False)
def load_pose():
    return build_pose_model()

POSE = load_pose()
cfg = render_sidebar()

st.markdown("""
<h1 style='text-align:center;color:#1E88E5;'>🧘 ErgoVision – Postura e Iluminación</h1>
<p style='text-align:center;color:#666;'>Dos modos de detección: <b>Lateral</b> y <b>Frontal</b></p>
""", unsafe_allow_html=True)
st.markdown("---")

tabs = st.tabs(["📷 Cámara lateral", "🧑‍💻 Cámara frontal"])

with tabs[0]:
    render_lateral(POSE=POSE, cfg=cfg)

with tabs[1]:
    render_frontal(POSE=POSE, cfg=cfg)

st.markdown("---")
st.markdown("""
<div style='text-align:center;color:#888'>
  <p>💡 Consejo: Para el modo lateral, ubica la cámara de perfil; para el frontal, colócala a la altura de los ojos y de frente.</p>
</div>
""", unsafe_allow_html=True)
