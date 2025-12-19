import streamlit as st
from common import build_pose_model, try_limit_opencv_threads
from sidebar_config import init_session_defaults, get_config
from mode_lateral import render_lateral
from mode_frontal import render_frontal
from history_view import render_history

st.set_page_config(
    page_title="ErgoVision - Smart Posture Monitor",
    page_icon="🧘",
    layout="wide",
    initial_sidebar_state="expanded"
)

try_limit_opencv_threads(2)

# Initialize session state
init_session_defaults()

@st.cache_resource(show_spinner=False)
def load_pose():
    return build_pose_model()

# Initialize theme
if 'theme' not in st.session_state:
    st.session_state.theme = 'dark'

# Nueva paleta de colores Samsung Innovation Campus
COLORS = {
    'ink_black': '#0c1618',      # Fondo oscuro principal
    'pine_teal': '#004643',      # Verde azulado oscuro
    'cornsilk': '#faf4d3',       # Crema/pastel claro
    'rosy_granite': '#92898a',   # Gris rosado
    'dark_cyan': '#119da4',      # Cyan brillante (acento)
    'white': '#ffffff',          # Blanco puro
    'light_teal': '#e6f4f4',     # Teal muy claro (para modo día)
}

# Custom CSS con nueva paleta de colores
def apply_theme():
    theme = st.session_state.theme
    
    if theme == 'dark':
        # MODO NOCHE
        bg_primary = COLORS['ink_black']
        bg_secondary = COLORS['pine_teal']
        text_primary = COLORS['cornsilk']
        text_secondary = COLORS['white']
        accent = COLORS['dark_cyan']
        border = COLORS['pine_teal']
        button_bg = COLORS['dark_cyan']
        button_text = COLORS['ink_black']
        sidebar_gradient_start = COLORS['pine_teal']
        sidebar_gradient_end = COLORS['ink_black']
    else:
        # MODO DÍA - Con tonalidades pasteles
        bg_primary = COLORS['cornsilk']
        bg_secondary = COLORS['light_teal']
        text_primary = COLORS['ink_black']
        text_secondary = COLORS['pine_teal']
        accent = COLORS['dark_cyan']
        border = COLORS['pine_teal']
        button_bg = COLORS['dark_cyan']
        button_text = COLORS['white']
        sidebar_gradient_start = COLORS['light_teal']
        sidebar_gradient_end = COLORS['cornsilk']
    
    st.markdown(f"""
    <style>
        /* Global Styles */
        .main {{
            background-color: {bg_primary};
            color: {text_primary};
        }}
        
        .stApp {{
            background-color: {bg_primary};
        }}
        
        /* Sidebar Styling */
        [data-testid="stSidebar"] {{
            background: linear-gradient(180deg, {sidebar_gradient_start} 0%, {sidebar_gradient_end} 100%);
            border-right: 2px solid {border};
        }}
        
        [data-testid="stSidebar"] h1,
        [data-testid="stSidebar"] h2,
        [data-testid="stSidebar"] h3,
        [data-testid="stSidebar"] label {{
            color: {text_primary} !important;
        }}
        
        [data-testid="stSidebar"] .stMarkdown {{
            color: {text_primary} !important;
        }}
        
        /* Header */
        .main-header {{
            text-align: center;
            padding: 2rem 0;
            background: linear-gradient(135deg, {accent}33 0%, {accent}11 100%);
            border-radius: 16px;
            margin-bottom: 2rem;
            border: 2px solid {border};
        }}
        
        .main-title {{
            font-size: 3.5rem;
            font-weight: 800;
            background: linear-gradient(135deg, {accent} 0%, {text_secondary} 100%);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            margin: 0;
            letter-spacing: -2px;
        }}
        
        .main-subtitle {{
            font-size: 1.2rem;
            color: {text_primary};
            opacity: 0.85;
            margin-top: 0.5rem;
            font-weight: 500;
        }}
        
        /* Tabs */
        .stTabs [data-baseweb="tab-list"] {{
            gap: 1rem;
            background-color: {bg_secondary};
            padding: 0.75rem;
            border-radius: 12px;
            border: 2px solid {border};
        }}
        
        .stTabs [data-baseweb="tab"] {{
            padding: 1rem 2rem;
            border-radius: 8px;
            font-weight: 700;
            font-size: 1.1rem;
            background-color: transparent;
            border: 2px solid transparent;
            color: {text_primary};
            transition: all 0.3s ease;
        }}
        
        .stTabs [data-baseweb="tab"]:hover {{
            background-color: {accent}33;
            border-color: {accent};
        }}
        
        .stTabs [aria-selected="true"] {{
            background-color: {accent};
            border-color: {accent};
            color: {button_text};
            box-shadow: 0 4px 12px {accent}66;
        }}
        
        /* Metric Cards */
        .metric-card {{
            background: {bg_secondary};
            border: 2px solid {border};
            border-radius: 16px;
            padding: 1.5rem;
            margin: 0.75rem 0;
            box-shadow: 0 4px 12px rgba(0,0,0,0.15);
            transition: all 0.3s ease;
        }}
        
        .metric-card:hover {{
            transform: translateY(-2px);
            box-shadow: 0 6px 16px rgba(0,0,0,0.2);
            border-color: {accent};
        }}
        
        .metric-title {{
            font-size: 0.875rem;
            font-weight: 700;
            text-transform: uppercase;
            letter-spacing: 1px;
            color: {text_secondary};
            opacity: 0.9;
            margin-bottom: 0.5rem;
        }}
        
        .metric-value {{
            font-size: 2.25rem;
            font-weight: 800;
            color: {text_primary};
            margin: 0.5rem 0;
            line-height: 1.2;
        }}
        
        .metric-label {{
            font-size: 1rem;
            color: {text_primary};
            opacity: 0.8;
            font-weight: 500;
        }}
        
        /* Status Colors - Ajustados para ambos temas */
        .status-good {{
            color: {accent};
            text-shadow: 0 0 10px {accent}44;
        }}
        
        .status-warning {{
            color: #f4a261;
            text-shadow: 0 0 10px #f4a26144;
        }}
        
        .status-error {{
            color: #e76f51;
            text-shadow: 0 0 10px #e76f5144;
        }}
        
        /* Video Container */
        .video-container {{
            border-radius: 16px;
            overflow: hidden;
            border: 3px solid {border};
            box-shadow: 0 8px 24px rgba(0,0,0,0.2);
            background: {bg_secondary};
        }}
        
        video {{
            border-radius: 16px;
        }}
        
        /* START Button - Nuevo color destacado */
        .stButton button {{
            border-radius: 12px;
            padding: 0.75rem 2rem;
            font-weight: 700;
            border: 2px solid {button_bg};
            background: {button_bg};
            color: {button_text};
            transition: all 0.3s ease;
            text-transform: uppercase;
            letter-spacing: 1px;
            font-size: 0.9rem;
        }}
        
        .stButton button:hover {{
            background: {accent};
            border-color: {accent};
            transform: translateY(-2px);
            box-shadow: 0 6px 20px {accent}66;
            color: {button_text};
        }}
        
        /* Botones específicos */
        button[kind="primary"] {{
            background: {button_bg} !important;
            border-color: {button_bg} !important;
            color: {button_text} !important;
        }}
        
        button[kind="primary"]:hover {{
            background: {accent} !important;
            border-color: {accent} !important;
            transform: translateY(-2px);
            box-shadow: 0 6px 20px {accent}66;
        }}
        
        /* Theme Toggle */
        .theme-toggle {{
            position: fixed;
            top: 1rem;
            right: 1rem;
            z-index: 999;
            background: {bg_secondary};
            border: 2px solid {border};
            border-radius: 50px;
            padding: 0.5rem 1rem;
            display: flex;
            gap: 0.5rem;
            box-shadow: 0 4px 12px rgba(0,0,0,0.15);
        }}
        
        .theme-btn {{
            background: transparent;
            border: none;
            font-size: 1.5rem;
            cursor: pointer;
            padding: 0.25rem 0.5rem;
            border-radius: 8px;
            transition: all 0.3s ease;
        }}
        
        .theme-btn:hover {{
            background: {accent}33;
            transform: scale(1.1);
        }}
        
        .theme-btn.active {{
            background: {accent};
            transform: scale(1.15);
        }}
        
        /* Info boxes - con mejor contraste */
        .stInfo {{
            background-color: {accent}22 !important;
            border-left: 4px solid {accent} !important;
            color: {text_primary} !important;
            border-radius: 8px !important;
        }}
        
        .stSuccess {{
            background-color: {accent}22 !important;
            border-left: 4px solid {accent} !important;
            color: {text_primary} !important;
            border-radius: 8px !important;
        }}
        
        .stWarning {{
            background-color: #f4a26122 !important;
            border-left: 4px solid #f4a261 !important;
            color: {text_primary} !important;
            border-radius: 8px !important;
        }}
        
        .stError {{
            background-color: #e76f5122 !important;
            border-left: 4px solid #e76f51 !important;
            color: {text_primary} !important;
            border-radius: 8px !important;
        }}
        
        /* Hide default elements */
        #MainMenu {{visibility: hidden;}}
        footer {{visibility: hidden;}}
        
        /* Sliders - mejor visibilidad */
        .stSlider {{
            padding: 1rem 0;
        }}
        
        .stSlider label {{
            color: {text_primary} !important;
            font-weight: 600;
        }}
        
        /* Checkboxes */
        .stCheckbox label {{
            font-weight: 600;
            color: {text_primary} !important;
        }}
        
        /* Expander */
        .streamlit-expanderHeader {{
            background: {bg_secondary} !important;
            border-radius: 8px;
            font-weight: 700;
            border: 2px solid {border};
            color: {text_primary} !important;
        }}
        
        /* Mejorar contraste de texto en general */
        p, span, div {{
            color: {text_primary};
        }}
        
        /* Caption text */
        .stCaption {{
            color: {text_primary} !important;
            opacity: 0.7;
        }}
        
        /* Footer personalizado */
        .custom-footer {{
            text-align: center;
            color: {text_secondary};
            padding: 1rem;
            background: {bg_secondary};
            border-radius: 12px;
            border: 2px solid {border};
            margin-top: 2rem;
        }}
    </style>
    """, unsafe_allow_html=True)

apply_theme()

# Theme Toggle (floating button)
theme_col1, theme_col2 = st.columns([10, 1])
with theme_col2:
    if st.session_state.theme == 'dark':
        if st.button("☀️", key="theme_toggle", help="Cambiar a modo día"):
            st.session_state.theme = 'light'
            st.rerun()
    else:
        if st.button("🌙", key="theme_toggle", help="Cambiar a modo noche"):
            st.session_state.theme = 'dark'
            st.rerun()

# Sidebar for Settings
with st.sidebar:
    st.markdown("## ⚙️ Configuración")
    
    with st.expander("💡 **Iluminación**", expanded=False):
        lighting_thresh = st.slider(
            "Umbral de brillo mínimo",
            min_value=10, max_value=120, value=55, step=1,
            help="Brillo mínimo recomendado (0-255)"
        )
    
    with st.expander("⚡ **Rendimiento**", expanded=False):
        process_every_n = st.slider(
            "Procesar cada N frames",
            min_value=1, max_value=6, value=1, step=1,
            help="Mayor número = menos CPU"
        )
        debug_overlay = st.checkbox("Mostrar puntos de tracking", value=True)
    
    with st.expander("📏 **Umbrales de Postura**", expanded=False):
        st.markdown("##### 🧑‍💻 Vista Frontal")
        fr_good = st.slider("✅ Buena ≥", 150.0, 180.0, 163.0, 0.1, key="fr_good")
        fr_fair = st.slider("⚠️ Regular ≥", 140.0, 179.9, 159.0, 0.1, key="fr_fair")
        
        st.markdown("##### 📷 Vista Lateral")
        lat_good = st.slider("✅ Buena ≥", 150.0, 180.0, 165.0, 0.1, key="lat_good")
        lat_fair = st.slider("⚠️ Regular ≥", 140.0, 179.9, 160.0, 0.1, key="lat_fair")
    
    with st.expander("⏰ **Alertas**", expanded=False):
        enable_posture_alerts = st.checkbox("🪑 Alertas de postura", value=True)
        posture_seconds = st.slider("Segundos de mala postura", 3, 20, 6, 1)
        good_seconds = st.slider("Segundos de buena postura para limpiar", 2, 10, 3, 1)
        
        enable_light_alerts = st.checkbox("💡 Alertas de iluminación", value=True)
        light_seconds = st.slider("Segundos de baja luz", 3, 20, 8, 1)
        good_light_seconds = st.slider("Segundos de buena luz para limpiar", 2, 10, 3, 1)
        
        cooldown_seconds = st.slider("Cool-down (seg)", 3, 60, 15, 1)
    
    with st.expander("🔔 **Notificaciones**", expanded=False):
        enable_desktop_notifications = st.checkbox("Notificaciones de escritorio", value=True)
        notification_cooldown_min = st.slider("Intervalo entre alertas (min)", 1, 30, 5, 1)
        st.session_state.notification_manager.cooldown = notification_cooldown_min * 60
        enable_notification_sound = st.checkbox("Reproducir sonidos", value=True)
    
    with st.expander("🌟 **Bienestar**", expanded=False):
        st.markdown("##### 💧 Hidratación")
        st.session_state.enable_hydration = st.checkbox("Activar recordatorio", value=True)
        st.session_state.hydrate_interval_min = st.slider(
            "Intervalo (min)", 2, 120, 45, 5
        )
        st.session_state.enable_drink_detection = st.checkbox(
            "Detección automática", value=True
        )
        st.caption("💡 El sistema es compartido entre ambas cámaras")
        
        if st.button("💧 Tomé agua ✅", use_container_width=True):
            import time
            # Actualizar ambos timestamps (compartido)
            st.session_state.last_drink_ts = time.time()
            st.session_state.last_drink_ts_front = time.time()
            st.session_state.has_drink_event = True
            st.session_state.has_drink_event_front = True
            st.session_state.drink_state = "far"
            st.session_state.drink_state_front = "far"
            st.session_state.near_time = 0.0
            st.session_state.near_time_front = 0.0
            st.session_state.hydration_alert_sent = False
            st.session_state.hydration_alert_sent_front = False
            st.success("✅ Hidratación registrada!")
        
        st.markdown("---")
        
        st.markdown("##### ⏳ Tiempo Sentado")
        st.session_state.enable_sitting_tracker = st.checkbox("Activar monitoreo", value=True)
        st.session_state.sitting_time_threshold_min = st.slider(
            "Alerta después de (min)", 5, 120, 30, 5
        )
        
        if st.button("⏳ Resetear contador", use_container_width=True):
            import time
            st.session_state.total_sitting_time = 0.0
            st.session_state.sitting_start_time = time.time()
            st.session_state.sitting_alert_sent = False
            st.success("✅ Contador reseteado!")
    
    with st.expander("📈 Historial", expanded=False):
        st.session_state.enable_history = st.checkbox(
            "Guardar sesiones en historial (SQLite)",
            value=st.session_state.enable_history,
            help="Guarda un resumen por sesión (sin video)."
        )
        st.session_state.history_db_path = st.text_input(
            "Archivo de base de datos",
            value=st.session_state.history_db_path,
            help="Ruta del archivo .db (por defecto: ergovision_sessions.db)."
        )

POSE = load_pose()

# Get configuration - Ahora con sistema compartido de hidratación
cfg = get_config(
    lighting_thresh=lighting_thresh,
    process_every_n=process_every_n,
    debug_overlay=debug_overlay,
    fr_good=fr_good,
    fr_fair=fr_fair,
    lat_good=lat_good,
    lat_fair=lat_fair,
    enable_posture_alerts=enable_posture_alerts,
    posture_seconds=posture_seconds,
    good_seconds=good_seconds,
    enable_light_alerts=enable_light_alerts,
    light_seconds=light_seconds,
    good_light_seconds=good_light_seconds,
    cooldown_seconds=cooldown_seconds,
    enable_desktop_notifications=enable_desktop_notifications,
    enable_notification_sound=enable_notification_sound
)

# Header
st.markdown(f"""
<div class="main-header">
    <h1 class="main-title">🧘 ErgoVision</h1>
    <p class="main-subtitle">Monitor inteligente de bienestar con IA</p>
</div>
""", unsafe_allow_html=True)

# Main tabs
tabs = st.tabs(["📷 Cámara lateral", "🧑‍💻 Cámara frontal", "📈 Historial"])

with tabs[0]:
    render_lateral(POSE=POSE, cfg=cfg)

with tabs[1]:
    render_frontal(POSE=POSE, cfg=cfg)

with tabs[2]:
    render_history(db_path=cfg.get("history_db_path","ergovision_sessions.db"))

# Footer mejorado con la paleta
st.markdown("---")
theme = st.session_state.theme
if theme == 'dark':
    footer_color = COLORS['dark_cyan']
else:
    footer_color = COLORS['pine_teal']

st.markdown(f"""
<div class="custom-footer">
    <p style='margin:0;font-weight:600;color:{footer_color};'>💡 <strong>Tip:</strong> Lateral = perfil | Frontal = de frente</p>
    <p style='margin:0.5rem 0 0 0;font-size:0.875rem;opacity:0.8;'>Desarrollado para Samsung Innovation Campus 2025</p>
</div>
""", unsafe_allow_html=True)