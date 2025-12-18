import streamlit as st
import streamlit.components.v1 as components
import cv2
import mediapipe as mp
import numpy as np
import time
from streamlit_webrtc import webrtc_streamer, WebRtcMode, RTCConfiguration
from notificaciones import NotificationManager, get_notification_message
import av
import threading


# Configuración de la página
st.set_page_config(
    page_title="Coach de Bienestar – Postura e Iluminación (Lateral & Frontal)",
    page_icon="🧘",
    layout="wide",
)

# Limitar hilos internos de OpenCV (opcional)
try:
    cv2.setNumThreads(2)
except Exception:
    pass


# MediaPipe
mp_pose = mp.solutions.pose
mp_drawing = mp.solutions.drawing_utils


# WebRTC
RTC_CONFIGURATION = RTCConfiguration(
    {"iceServers": [{"urls": ["stun:stun.l.google.com:19302"]}]}
)


# Utilidades
class EMA:
    def __init__(self, alpha=0.3, initial=None):
        self.alpha = float(alpha)
        self.value = initial

    def update(self, x):
        if x is None:
            return self.value
        if self.value is None:
            self.value = float(x)
        else:
            self.value = self.alpha * float(x) + (1.0 - self.alpha) * self.value
        return self.value


def calculate_angle(a, b, c):
    a = np.array(a, dtype=np.float32)
    b = np.array(b, dtype=np.float32)
    c = np.array(c, dtype=np.float32)
    radians = np.arctan2(c[1] - b[1], c[0] - b[0]) - np.arctan2(a[1] - b[1], a[0] - b[0])
    angle = np.abs(radians * 180.0 / np.pi)
    if angle > 180.0:
        angle = 360.0 - angle
    return float(angle)


def angle_with_vertical(p_sh, p_ear):
    v = np.array([p_ear[0] - p_sh[0], p_ear[1] - p_sh[1]], dtype=np.float32)
    vert = np.array([0.0, -1.0], dtype=np.float32)
    dot = float(np.dot(v, vert))
    nv = float(np.linalg.norm(v)) + 1e-9
    na = float(np.linalg.norm(vert))
    theta = np.degrees(np.arccos(np.clip(dot / (nv * na), -1.0, 1.0)))
    return 180.0 - theta


def js_beep(freq=880, duration=0.12, vol=0.18):
    st.markdown(
        f"<script>window.playBeep && window.playBeep({freq}, {duration}, 'sine', {vol});</script>",
        unsafe_allow_html=True,
    )


# Pose (única instancia)
pose_lock = threading.Lock()


@st.cache_resource(show_spinner=False)
def load_pose_model():
    return mp_pose.Pose(
        static_image_mode=False,
        model_complexity=1,
        enable_segmentation=False,
        min_detection_confidence=0.5,
        min_tracking_confidence=0.5,
    )


POSE = load_pose_model()


# Estados y EMAs
def new_shared_state():
    return {
        "posture_msg": "Inicializando...",
        "posture_icon": "🟡",
        "neck_angle_raw": None,
        "neck_angle_smooth": None,
        "brightness_raw": 0.0,
        "brightness_smooth": 0.0,
        "lighting_ok": True,
        "last_update_ts": 0.0,

        # NUEVO: distancia muñeca->nariz (proxy) para hidratación (solo frontal)
        "wrist_mouth_dist": None,
    }


def reset_shared(shared, neck_ema_obj, bright_ema_obj):
    shared.update({
        "posture_msg": "Inicializando...",
        "posture_icon": "🟡",
        "neck_angle_raw": None,
        "neck_angle_smooth": None,
        "brightness_raw": 0.0,
        "brightness_smooth": 0.0,
        "lighting_ok": True,
        "last_update_ts": 0.0,
        "wrist_mouth_dist": None,
    })
    neck_ema_obj.value = None
    bright_ema_obj.value = 60.0


shared_lock_side = threading.Lock()
shared_lock_front = threading.Lock()
shared_side = new_shared_state()
shared_front = new_shared_state()
neck_ema_side = EMA(alpha=0.35, initial=None)
neck_ema_front = EMA(alpha=0.35, initial=None)
bright_ema_side = EMA(alpha=0.25, initial=60.0)
bright_ema_front = EMA(alpha=0.25, initial=60.0)
frame_count_side = {"n": 0}
frame_count_front = {"n": 0}

# Flags de reseteo
if "side_reset_done" not in st.session_state:
    st.session_state.side_reset_done = False
if "front_reset_done" not in st.session_state:
    st.session_state.front_reset_done = False

# Timers y flags (existentes)
for key, default in [
    ("bad_timer_side", 0.0), ("bad_timer_front", 0.0),
    ("bad_cool_side", 0.0), ("bad_cool_front", 0.0),
    ("lowlight_timer_side", 0.0), ("lowlight_timer_front", 0.0),
    ("lowlight_cool_side", 0.0), ("lowlight_cool_front", 0.0),
    ("good_timer_side", 0.0), ("good_timer_front", 0.0),
    ("posture_alert_active_side", False), ("posture_alert_active_front", False),
    ("goodlight_timer_side", 0.0), ("goodlight_timer_front", 0.0),
    ("light_alert_active_side", False), ("light_alert_active_front", False),
    ("last_tick_side", time.time()), ("last_tick_front", time.time()),
    ("sound_ready", False),
]:
    if key not in st.session_state:
        st.session_state[key] = default

# Inicializar las notificaciones
if "notification_manager" not in st.session_state:
    st.session_state.notification_manager = NotificationManager(cooldown_seconds=300)

# ===== NUEVO: estados hidratación FRONTAL (ligero) =====
for key, default in [
    ("enable_hydration_front", True),
    ("enable_drink_detection_front", True),
    ("hydrate_interval_min_front", 45),
    ("last_drink_ts_front", time.time()),
    ("has_drink_event_front", False),   # <- para mostrar "detectada hace"
    ("drink_state_front", "far"),       # "far" o "near"
    ("near_time_front", 0.0),
]:
    if key not in st.session_state:
        st.session_state[key] = default


# ========= Sidebar (ajustes) =========
with st.sidebar:
    st.header("⚙️ Configuración")

    st.subheader("Iluminación (0–255)")
    lighting_thresh = st.slider(
        "Umbral de brillo mínimo",
        min_value=10, max_value=120, value=55, step=1,
        help="Brillo mínimo recomendado para evitar fatiga visual."
    )

    st.subheader("Rendimiento")
    process_every_n = st.slider(
        "Procesar cada N cuadros",
        min_value=1, max_value=6, value=1, step=1,
        help="Procesa un cuadro y salta N-1 para ahorrar CPU."
    )
    debug_overlay = st.checkbox("Mostrar puntos y textos sobre el video", value=True)

    # === Umbrales de Postura ajustables por modo ===
    st.subheader("Umbrales de Postura (ajustables)")
    st.markdown("Define los ángulos del cuello para clasificar **Buena / Regular / Mala**.")

    fr_good_default = 163.0
    fr_fair_default = 159.0
    lat_good_default = 165.0
    lat_fair_default = 160.0

    fr_good = st.slider("Frontal – 'Buena'", 150.0, 180.0, fr_good_default, 0.1)
    fr_fair = st.slider("Frontal – 'Regular'", 140.0, 179.9, fr_fair_default, 0.1)

    lat_good = st.slider("Lateral – 'Buena'", 150.0, 180.0, lat_good_default, 0.1)
    lat_fair = st.slider("Lateral – 'Regular'", 140.0, 179.9, lat_fair_default, 0.1)

    if fr_fair >= fr_good:
        st.warning("⚠️ En Frontal, el umbral de 'Regular' debe ser menor que el de 'Buena'. Ajustando automáticamente.")
        fr_fair = max(140.0, fr_good - 0.1)
    if lat_fair >= lat_good:
        st.warning("⚠️ En Lateral, el umbral de 'Regular' debe ser menor que el de 'Buena'. Ajustando automáticamente.")
        lat_fair = max(140.0, lat_good - 0.1)

    st.caption(
        f"**Frontal**: Buena ≥ **{fr_good:.1f}°**, Regular **{fr_fair:.1f}–{fr_good - 0.1:.1f}°**, Mala < **{fr_fair:.1f}°**\n\n"
        f"**Lateral**: Buena ≥ **{lat_good:.1f}°**, Regular **{lat_fair:.1f}–{lat_good - 0.1:.1f}°**, Mala < **{lat_fair:.1f}°**"
    )

    # Controles de alertas
    st.subheader("Alertas")
    enable_posture_alerts = st.checkbox("Activar alertas por mala postura", value=True)
    posture_seconds = st.slider("Segundos de mala postura para alertar", 3, 20, 6, 1)
    good_seconds = 3

    enable_light_alerts = st.checkbox("Activar alertas por baja iluminación", value=True)
    light_seconds = st.slider("Segundos de baja luz para alertar", 3, 20, 8, 1)
    good_light_seconds = 3

    cooldown_seconds = st.slider("Tiempo de espera entre alertas (cool-down)", 3, 60, 15, 1)

    st.subheader("🔔 Notificaciones de Escritorio")
    enable_desktop_notifications = st.checkbox(
        "Activar notificaciones de escritorio",
        value=True,
        help="Envía alertas al sistema incluso si no estás viendo el dashboard"
    )

    notification_cooldown_min = st.slider(
        "Intervalo entre notificaciones (minutos)",
        1, 30, 5, 1,
        help="Tiempo mínimo entre notificaciones del mismo tipo"
    )

    st.session_state.notification_manager.cooldown = notification_cooldown_min * 60

    enable_notification_sound = st.checkbox(
        "Reproducir sonido del sistema",
        value=True,
        help="Reproduce sonidos nativos del sistema operativo"
    )

    if "notification_manager" not in st.session_state:
        st.session_state.notification_manager = NotificationManager(cooldown_seconds=cooldown_seconds)

    # ===== NUEVO: Hidratación (solo frontal) =====
    st.subheader("💧 Hidratación (Frontal)")
    st.session_state.enable_hydration_front = st.checkbox(
        "Activar hidratación (frontal)",
        value=st.session_state.enable_hydration_front
    )
    st.session_state.hydrate_interval_min_front = st.slider(
        "Intervalo (min)",
        10, 120,
        int(st.session_state.hydrate_interval_min_front),
        5
    )
    st.session_state.enable_drink_detection_front = st.checkbox(
        "Detectar gesto de beber (beta)",
        value=st.session_state.enable_drink_detection_front
    )

    # Botón manual para pruebas rápidas y para demo (muy confiable)
    if st.button("Tomé agua ✅ (manual)", key="drink_btn_sidebar_front"):
        st.session_state.last_drink_ts_front = time.time()
        st.session_state.has_drink_event_front = True
        st.session_state.drink_state_front = "far"
        st.session_state.near_time_front = 0.0
        st.success("Hidratación registrada (frontal).")


# Umbrales (dinámicos)
FRONTAL_GOOD_MIN = float(fr_good)
FRONTAL_FAIR_MIN = float(fr_fair)
LATERAL_GOOD_MIN = float(lat_good)
LATERAL_FAIR_MIN = float(lat_fair)


# Ángulos por modo
def neck_angle_side_best(lmk, min_vis=0.3):
    L_EAR = mp_pose.PoseLandmark.LEFT_EAR.value
    L_SH = mp_pose.PoseLandmark.LEFT_SHOULDER.value
    L_HIP = mp_pose.PoseLandmark.LEFT_HIP.value
    R_EAR = mp_pose.PoseLandmark.RIGHT_EAR.value
    R_SH = mp_pose.PoseLandmark.RIGHT_SHOULDER.value
    R_HIP = mp_pose.PoseLandmark.RIGHT_HIP.value

    def side(e, s, h):
        ve = lmk[e].visibility
        vs = lmk[s].visibility
        vh = lmk[h].visibility
        p_e = (lmk[e].x, lmk[e].y)
        p_s = (lmk[s].x, lmk[s].y)
        if min(ve, vs, vh) >= min_vis:
            p_h = (lmk[h].x, lmk[h].y)
            return calculate_angle(p_e, p_s, p_h)
        if min(ve, vs) >= min_vis:
            return angle_with_vertical(p_s, p_e)
        if min(ve, vs) >= 0.15:
            return angle_with_vertical(p_s, p_e)
        return None

    aL = side(L_EAR, L_SH, L_HIP)
    aR = side(R_EAR, R_SH, R_HIP)
    if aL is not None and aR is not None:
        return max(aL, aR)
    return aL if aL is not None else aR


def neck_angle_front_best(lmk, min_vis=0.3):
    L_EAR = mp_pose.PoseLandmark.LEFT_EAR.value
    L_SH = mp_pose.PoseLandmark.LEFT_SHOULDER.value
    R_EAR = mp_pose.PoseLandmark.RIGHT_EAR.value
    R_SH = mp_pose.PoseLandmark.RIGHT_SHOULDER.value

    def side(e, s):
        ve = lmk[e].visibility
        vs = lmk[s].visibility
        if min(ve, vs) < min_vis and min(ve, vs) < 0.15:
            return None
        p_e = (lmk[e].x, lmk[e].y)
        p_s = (lmk[s].x, lmk[s].y)
        return angle_with_vertical(p_s, p_e)

    aL = side(L_EAR, L_SH)
    aR = side(R_EAR, R_SH)
    if aL is not None and aR is not None:
        return max(aL, aR)
    return aL if aL is not None else aR


# Clasificación simple
def classify_posture_by_mode(angle_s, mode):
    if angle_s is None:
        return "No se detecta postura", "⚪"
    if mode == "front":
        if angle_s >= FRONTAL_GOOD_MIN:
            return "Buena postura", "🟢"
        if angle_s >= FRONTAL_FAIR_MIN:
            return "Postura regular", "🟡"
        return "MALA POSTURA", "🔴"
    else:
        if angle_s >= LATERAL_GOOD_MIN:
            return "Buena postura", "🟢"
        if angle_s >= LATERAL_FAIR_MIN:
            return "Postura regular", "🟡"
        return "MALA POSTURA", "🔴"


def posture_category_for_panel(angle_value, mode):
    if angle_value is None:
        good_thr = FRONTAL_GOOD_MIN if mode == "front" else LATERAL_GOOD_MIN
        return ("Sin datos de postura", "none", good_thr)
    if mode == "front":
        good_thr = FRONTAL_GOOD_MIN
        if angle_value >= FRONTAL_GOOD_MIN:
            return ("Buena postura", "good", good_thr)
        if angle_value >= FRONTAL_FAIR_MIN:
            return ("Postura regular", "regular", good_thr)
        return ("MALA POSTURA", "bad", good_thr)
    else:
        good_thr = LATERAL_GOOD_MIN
        if angle_value >= LATERAL_GOOD_MIN:
            return ("Buena postura", "good", good_thr)
        if angle_value >= LATERAL_FAIR_MIN:
            return ("Postura regular", "regular", good_thr)
        return ("MALA POSTURA", "bad", good_thr)


# Iluminación: categorización
def lighting_category(bright_smooth, thr):
    if bright_smooth is None:
        return ("Sin datos de luz", "none")
    good_min = thr + 15
    if bright_smooth < thr:
        return (f"Mala iluminación ({bright_smooth:.1f}/255)", "bad")
    elif bright_smooth < good_min:
        return (f"Iluminación regular ({bright_smooth:.1f}/255)", "regular")
    else:
        return (f"Buena iluminación ({bright_smooth:.1f}/255)", "good")


# Análisis
def analyze(img_bgr, last_msg, last_bright, angle_fn, neck_ema_obj, bright_ema_obj, mode_label, compute_wrist_mouth=False):
    rgb = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2RGB)
    with pose_lock:
        res = POSE.process(rgb)

    neck_angle = None
    wrist_mouth_dist = None

    if res.pose_landmarks:
        lmk = res.pose_landmarks.landmark
        try:
            neck_angle = angle_fn(lmk)
        except Exception:
            neck_angle = None

        # SOLO si lo pedimos (modo frontal)
        if compute_wrist_mouth:
            try:
                NOSE = mp_pose.PoseLandmark.NOSE.value
                LW = mp_pose.PoseLandmark.LEFT_WRIST.value
                RW = mp_pose.PoseLandmark.RIGHT_WRIST.value

                nose = np.array([lmk[NOSE].x, lmk[NOSE].y], dtype=np.float32)

                dists = []
                for W in (LW, RW):
                    if lmk[W].visibility >= 0.15:
                        w = np.array([lmk[W].x, lmk[W].y], dtype=np.float32)
                        dists.append(float(np.linalg.norm(w - nose)))
                wrist_mouth_dist = min(dists) if dists else None
            except Exception:
                wrist_mouth_dist = None

    neck_s = neck_ema_obj.update(neck_angle)
    posture_msg, posture_icon = classify_posture_by_mode(neck_s, mode_label)

    small = cv2.resize(img_bgr, (96, 54), interpolation=cv2.INTER_AREA)
    Y = (0.2126 * small[:, :, 2].astype(np.float32) +
         0.7152 * small[:, :, 1].astype(np.float32) +
         0.0722 * small[:, :, 0].astype(np.float32))
    bright = float(np.mean(Y))
    bright_s = bright_ema_obj.update(bright)
    lighting_ok = (bright_s is not None) and (bright_s >= lighting_thresh)

    return res, {
        "posture_msg": posture_msg,
        "posture_icon": posture_icon,
        "neck_angle_raw": neck_angle,
        "neck_angle_smooth": neck_s,
        "brightness_raw": bright,
        "brightness_smooth": bright_s,
        "lighting_ok": lighting_ok,
        "wrist_mouth_dist": wrist_mouth_dist,
    }


# Callback por modo
ORANGE = (0, 140, 255)


def make_callback(mode, shared, lock, frame_counter, neck_ema_obj, bright_ema_obj):
    if mode == "side":
        angle_fn = neck_angle_side_best
        title_msg = "Modo lateral"
        mode_label = "side"
        compute_wrist_mouth = False  # NO lo hacemos en lateral
    else:
        angle_fn = neck_angle_front_best
        title_msg = "Modo frontal"
        mode_label = "front"
        compute_wrist_mouth = True   # SOLO frontal

    def callback(frame: av.VideoFrame):
        img = frame.to_ndarray(format="bgr24")
        frame_counter["n"] += 1
        should_process = (frame_counter["n"] % process_every_n == 0)

        if should_process:
            with lock:
                last_msg = shared.get("posture_msg")
                last_bright = shared.get("brightness_smooth")

            res, data = analyze(
                img, last_msg, last_bright,
                angle_fn, neck_ema_obj, bright_ema_obj,
                mode_label,
                compute_wrist_mouth=compute_wrist_mouth
            )

            if debug_overlay:
                if res.pose_landmarks:
                    mp_drawing.draw_landmarks(
                        img, res.pose_landmarks, mp_pose.POSE_CONNECTIONS,
                        mp_drawing.DrawingSpec(color=(0, 255, 0), thickness=2),
                        mp_drawing.DrawingSpec(color=(0, 0, 255), thickness=2),
                    )
                cv2.putText(img, title_msg, (10, 30),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.9, ORANGE, 2, cv2.LINE_AA)

            with lock:
                shared.update(data)
                shared["last_update_ts"] = time.time()

            return av.VideoFrame.from_ndarray(img, format="bgr24")
        else:
            if debug_overlay:
                cv2.putText(img, title_msg, (10, 30),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.9, ORANGE, 2, cv2.LINE_AA)
            return av.VideoFrame.from_ndarray(img, format="bgr24")

    return callback


# UI
st.markdown("""
<h1 style='text-align:center;color:#1E88E5;'>🧘 Coach de Bienestar – Postura e Iluminación</h1>
<p style='text-align:center;color:#666;'>Dos modos de detección: <b>Lateral </b> y <b>Frontal </b></p>
""", unsafe_allow_html=True)
st.markdown("---")

tabs = st.tabs(["📷 Cámara lateral", "🧑‍💻 Cámara frontal"])

# ----------------- LATERAL -----------------
with tabs[0]:
    colV, colS = st.columns([2, 1])
    with colV:
        st.subheader("Cámara Lateral")
        cb_side = make_callback("side", shared_side, shared_lock_side, frame_count_side, neck_ema_side, bright_ema_side)
        webrtc_ctx_side = webrtc_streamer(
            key="posture-light-side",
            mode=WebRtcMode.SENDRECV,
            rtc_configuration=RTC_CONFIGURATION,
            video_frame_callback=cb_side,
            media_stream_constraints={"video": {"width": 640, "height": 360, "frameRate": 15}, "audio": False},
            async_processing=True,
        )

        if webrtc_ctx_side.state.playing and not st.session_state.side_reset_done:
            reset_shared(shared_side, neck_ema_side, bright_ema_side)

            now = time.time()
            st.session_state.last_tick_side = now
            st.session_state.bad_timer_side = 0.0
            st.session_state.lowlight_timer_side = 0.0
            st.session_state.good_timer_side = 0.0
            st.session_state.goodlight_timer_side = 0.0
            st.session_state.posture_alert_active_side = False
            st.session_state.light_alert_active_side = False
            st.session_state.bad_cool_side = 0.0
            st.session_state.lowlight_cool_side = 0.0

            st.session_state.side_reset_done = True
        elif not webrtc_ctx_side.state.playing and st.session_state.side_reset_done:
            st.session_state.side_reset_done = False

    with colS:
        st.subheader("Estado ")
        panel_lat = st.empty()
        alert_ph_side = st.empty()
        alert_light_ph_side = st.empty()

        if webrtc_ctx_side.state.playing:
            while webrtc_ctx_side.state.playing:
                with shared_lock_side:
                    nang = shared_side["neck_angle_smooth"]
                    nraw = shared_side["neck_angle_raw"]
                    bsmo = shared_side["brightness_smooth"]

                with panel_lat.container():
                    # ---- Postura ----
                    st.markdown("### Postura")
                    ang_side_now = nang if nang is not None else nraw
                    p_label, p_level, _ = posture_category_for_panel(ang_side_now, "side")
                    if p_level == "good":
                        st.success(p_label)
                    elif p_level == "regular":
                        st.warning(p_label)
                    elif p_level == "bad":
                        st.error(p_label)
                    else:
                        st.info(p_label)

                    if ang_side_now is not None:
                        st.write(f"Ángulo del cuello: **{ang_side_now:.1f}°**")
                    else:
                        st.write("Esperando detección…")

                    # ---- Iluminación ----
                    st.markdown("### 💡 Iluminación")
                    label, level = lighting_category(bsmo, lighting_thresh)
                    if level == "good":
                        st.success(label)
                    elif level == "regular":
                        st.warning(label)
                    elif level == "bad":
                        st.error(label)
                    else:
                        st.info(label)
                    st.caption(f"Mínimo umbral: {lighting_thresh} (Buena ≥ {lighting_thresh + 15})")

                    # Tiempo transcurrido (clamp)
                    now = time.time()
                    dt_raw = now - st.session_state.last_tick_side
                    dt = min(max(dt_raw, 0.0), 0.5)
                    st.session_state.last_tick_side = now

                    # Postura
                    if enable_posture_alerts:
                        if p_level == "bad":
                            st.session_state.bad_timer_side += dt
                            st.session_state.good_timer_side = max(0.0, st.session_state.good_timer_side - dt * 0.5)
                        elif p_level == "good":
                            st.session_state.good_timer_side += dt
                            st.session_state.bad_timer_side = max(0.0, st.session_state.bad_timer_side - dt * 0.5)
                        else:
                            st.session_state.bad_timer_side = max(0.0, st.session_state.bad_timer_side - dt * 0.3)
                            st.session_state.good_timer_side = max(0.0, st.session_state.good_timer_side - dt * 0.3)

                        if (st.session_state.bad_timer_side >= posture_seconds) and (now >= st.session_state.bad_cool_side) and (not st.session_state.posture_alert_active_side):
                            alert_ph_side.error("⚠️ ⚠️ Mala postura mantenida. Endereza cuello y la espalda.")
                            st.session_state.posture_alert_active_side = True
                            st.session_state.bad_timer_side = 0.0
                            st.session_state.bad_cool_side = now + cooldown_seconds

                            # Notificación de escritorio
                            if enable_desktop_notifications:
                                msg = get_notification_message('posture_bad_side')
                                st.session_state.notification_manager.send(
                                    'posture_bad_side',
                                    msg['title'],
                                    msg['message'],
                                    sound_type=msg['sound'],
                                    play_sound=enable_notification_sound
                                )

                        if st.session_state.posture_alert_active_side and (p_level == "good") and (st.session_state.good_timer_side >= good_seconds):
                            alert_ph_side.empty()
                            st.session_state.posture_alert_active_side = False

                    # Luz
                    if enable_light_alerts:
                        if level == "bad":
                            st.session_state.lowlight_timer_side += dt
                            st.session_state.goodlight_timer_side = max(0.0, st.session_state.goodlight_timer_side - dt * 0.5)
                        elif level == "good":
                            st.session_state.goodlight_timer_side += dt
                            st.session_state.lowlight_timer_side = max(0.0, st.session_state.lowlight_timer_side - dt * 0.5)
                        else:
                            st.session_state.lowlight_timer_side = max(0.0, st.session_state.lowlight_timer_side - dt * 0.3)
                            st.session_state.goodlight_timer_side = max(0.0, st.session_state.goodlight_timer_side - dt * 0.3)

                        if (st.session_state.lowlight_timer_side >= light_seconds) and (now >= st.session_state.lowlight_cool_side) and (not st.session_state.light_alert_active_side):
                            alert_light_ph_side.warning("💡 Iluminación insuficiente. Aumenta el nivel de luz en la habitación o ajusta el umbral.")
                            st.session_state.light_alert_active_side = True
                            st.session_state.lowlight_timer_side = 0.0
                            st.session_state.lowlight_cool_side = now + cooldown_seconds

                            # Notificación de escritorio
                            if enable_desktop_notifications:
                                msg = get_notification_message('lighting_low_side')
                                st.session_state.notification_manager.send(
                                    'lighting_low_side',
                                    msg['title'],
                                    msg['message'],
                                    sound_type=msg['sound'],
                                    play_sound=enable_notification_sound
                                )

                        if st.session_state.light_alert_active_side and (level == "good") and (st.session_state.goodlight_timer_side >= good_light_seconds):
                            alert_light_ph_side.empty()
                            st.session_state.light_alert_active_side = False

                time.sleep(0.2)
        else:
            st.info("Inicia la cámara para este modo.")

# ----------------- FRONTAL -----------------
with tabs[1]:
    colV2, colS2 = st.columns([2, 1])
    with colV2:
        st.subheader("Cámara Frontal")
        cb_front = make_callback("front", shared_front, shared_lock_front, frame_count_front, neck_ema_front, bright_ema_front)
        webrtc_ctx_front = webrtc_streamer(
            key="posture-light-front",
            mode=WebRtcMode.SENDRECV,
            rtc_configuration=RTC_CONFIGURATION,
            video_frame_callback=cb_front,
            media_stream_constraints={"video": {"width": 640, "height": 360, "frameRate": 15}, "audio": False},
            async_processing=True,
        )

        if webrtc_ctx_front.state.playing and not st.session_state.front_reset_done:
            reset_shared(shared_front, neck_ema_front, bright_ema_front)

            now = time.time()
            st.session_state.last_tick_front = now
            st.session_state.bad_timer_front = 0.0
            st.session_state.lowlight_timer_front = 0.0
            st.session_state.good_timer_front = 0.0
            st.session_state.goodlight_timer_front = 0.0
            st.session_state.posture_alert_active_front = False
            st.session_state.light_alert_active_front = False
            st.session_state.bad_cool_front = 0.0
            st.session_state.lowlight_cool_front = 0.0

            # Reset hidratación frontal al iniciar cámara
            st.session_state.last_drink_ts_front = time.time()
            st.session_state.has_drink_event_front = False
            st.session_state.drink_state_front = "far"
            st.session_state.near_time_front = 0.0

            st.session_state.front_reset_done = True
        elif not webrtc_ctx_front.state.playing and st.session_state.front_reset_done:
            st.session_state.front_reset_done = False

    with colS2:
        st.subheader("Estado ")
        panel_front = st.empty()
        alert_ph_front = st.empty()
        alert_light_ph_front = st.empty()

        if webrtc_ctx_front.state.playing:
            while webrtc_ctx_front.state.playing:
                with shared_lock_front:
                    nang = shared_front["neck_angle_smooth"]
                    nraw = shared_front["neck_angle_raw"]
                    bsmo = shared_front["brightness_smooth"]
                    wd = shared_front.get("wrist_mouth_dist", None)

                with panel_front.container():
                    # ---- Postura ----
                    st.markdown("### Postura")
                    ang_front_now = nang if nang is not None else nraw
                    p_label, p_level, _ = posture_category_for_panel(ang_front_now, "front")
                    if p_level == "good":
                        st.success(p_label)
                    elif p_level == "regular":
                        st.warning(p_label)
                    elif p_level == "bad":
                        st.error(p_label)
                    else:
                        st.info(p_label)

                    if ang_front_now is not None:
                        st.write(f"Ángulo del cuello: **{ang_front_now:.1f}°**")
                    else:
                        st.write("Esperando detección…")

                    # ---- Iluminación ----
                    st.markdown("### 💡 Iluminación")
                    label, level = lighting_category(bsmo, lighting_thresh)
                    if level == "good":
                        st.success(label)
                    elif level == "regular":
                        st.warning(label)
                    elif level == "bad":
                        st.error(label)
                    else:
                        st.info(label)
                    st.caption(f"Mínimo umbral: {lighting_thresh} (Buena ≥ {lighting_thresh + 15})")

                    # ====== Tiempo transcurrido (clamp) ======
                    now = time.time()
                    dt_raw = now - st.session_state.last_tick_front
                    dt = min(max(dt_raw, 0.0), 0.5)
                    st.session_state.last_tick_front = now

                    # ====== Postura ======
                    if enable_posture_alerts:
                        if p_level == "bad":
                            st.session_state.bad_timer_front += dt
                            st.session_state.good_timer_front = max(0.0, st.session_state.good_timer_front - dt * 0.5)
                        elif p_level == "good":
                            st.session_state.good_timer_front += dt
                            st.session_state.bad_timer_front = max(0.0, st.session_state.bad_timer_front - dt * 0.5)
                        else:
                            st.session_state.bad_timer_front = max(0.0, st.session_state.bad_timer_front - dt * 0.3)
                            st.session_state.good_timer_front = max(0.0, st.session_state.good_timer_front - dt * 0.3)

                        if (st.session_state.bad_timer_front >= posture_seconds) and (now >= st.session_state.bad_cool_front) and (not st.session_state.posture_alert_active_front):
                            alert_ph_front.error("⚠️ Mala postura mantenida. Endereza cuello y la espalda.")
                            st.session_state.posture_alert_active_front = True
                            st.session_state.bad_timer_front = 0.0
                            st.session_state.bad_cool_front = now + cooldown_seconds

                            # Notificación de escritorio
                            if enable_desktop_notifications:
                                msg = get_notification_message('posture_bad_front')
                                st.session_state.notification_manager.send(
                                    'posture_bad_front',
                                    msg['title'],
                                    msg['message'],
                                    sound_type=msg['sound'],
                                    play_sound=enable_notification_sound
                                )

                        if st.session_state.posture_alert_active_front and (p_level == "good") and (st.session_state.good_timer_front >= good_seconds):
                            alert_ph_front.empty()
                            st.session_state.posture_alert_active_front = False

                    # ====== Luz ======
                    if enable_light_alerts:
                        if level == "bad":
                            st.session_state.lowlight_timer_front += dt
                            st.session_state.goodlight_timer_front = max(0.0, st.session_state.goodlight_timer_front - dt * 0.5)
                        elif level == "good":
                            st.session_state.goodlight_timer_front += dt
                            st.session_state.lowlight_timer_front = max(0.0, st.session_state.lowlight_timer_front - dt * 0.5)
                        else:
                            st.session_state.lowlight_timer_front = max(0.0, st.session_state.lowlight_timer_front - dt * 0.3)
                            st.session_state.goodlight_timer_front = max(0.0, st.session_state.goodlight_timer_front - dt * 0.3)

                        if (st.session_state.lowlight_timer_front >= light_seconds) and (now >= st.session_state.lowlight_cool_front) and (not st.session_state.light_alert_active_front):
                            alert_light_ph_front.warning("💡 Iluminación insuficiente. Aumenta el nivel de luz en la habitación o ajusta el umbral.")
                            st.session_state.light_alert_active_front = True
                            st.session_state.lowlight_timer_front = 0.0
                            st.session_state.lowlight_cool_front = now + cooldown_seconds

                            # Notificación de escritorio
                            if enable_desktop_notifications:
                                msg = get_notification_message('lighting_low_front')
                                st.session_state.notification_manager.send(
                                    'lighting_low_front',
                                    msg['title'],
                                    msg['message'],
                                    sound_type=msg['sound'],
                                    play_sound=enable_notification_sound
                                )

                        if st.session_state.light_alert_active_front and (level == "good") and (st.session_state.goodlight_timer_front >= good_light_seconds):
                            alert_light_ph_front.empty()
                            st.session_state.light_alert_active_front = False

                    # ====== HIDRATACIÓN (FRONTAL) – LIGERO + AUTORESET ======
                    st.markdown("### 💧 Hidratación (Frontal)")

                    if st.session_state.enable_hydration_front:
                        interval_min = float(st.session_state.hydrate_interval_min_front)

                        # Detección beta (far -> near -> far) con anti "mano en cara"
                        if st.session_state.enable_drink_detection_front and (wd is not None):
                            D_NEAR = 0.09
                            D_FAR = 0.14
                            T_MIN = 0.6
                            T_MAX = 2.0
                            T_FACE = 3.5

                            state = st.session_state.drink_state_front

                            if state == "far":
                                if wd < D_NEAR:
                                    st.session_state.drink_state_front = "near"
                                    st.session_state.near_time_front = 0.0

                            elif state == "near":
                                st.session_state.near_time_front += dt

                                # si dura demasiado cerca: mano en cara
                                if st.session_state.near_time_front > T_FACE:
                                    st.session_state.drink_state_front = "far"
                                    st.session_state.near_time_front = 0.0

                                # si se alejó, evaluar evento
                                if wd > D_FAR:
                                    t = st.session_state.near_time_front
                                    if (t >= T_MIN) and (t <= T_MAX):
                                        # ✅ Detectó "tomó agua" => reinicia automático
                                        st.session_state.last_drink_ts_front = now
                                        st.session_state.has_drink_event_front = True

                                    st.session_state.drink_state_front = "far"
                                    st.session_state.near_time_front = 0.0

                        # Mostrar estado: "detectada hace X min"
                        if st.session_state.has_drink_event_front:
                            elapsed_min = (now - st.session_state.last_drink_ts_front) / 60.0
                            elapsed_min = max(0.0, elapsed_min)
                            st.write(f"**Hidratación detectada hace:** {elapsed_min:.0f} min (intervalo: {interval_min:.0f} min)")
                        else:
                            st.write(f"**Hidratación:** sin detección todavía (intervalo: {interval_min:.0f} min)")
                    else:
                        st.info("Hidratación desactivada (frontal).")

                time.sleep(0.2)
        else:
            st.info("Inicia la cámara para este modo.")

st.markdown("---")
st.markdown("""
<div style='text-align:center;color:#888'>
  <p>💡 Consejo: Para el modo lateral, ubica la cámara de perfil; para el frontal, colócala a la altura de los ojos y de frente.</p>
</div>
""", unsafe_allow_html=True)
