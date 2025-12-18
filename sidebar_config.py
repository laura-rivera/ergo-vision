import time
import streamlit as st
from notificaciones import NotificationManager

def init_session_defaults():
    st.session_state.setdefault("side_reset_done", False)
    st.session_state.setdefault("front_reset_done", False)

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
    ]:
        st.session_state.setdefault(key, default)

    if "notification_manager" not in st.session_state:
        st.session_state.notification_manager = NotificationManager(cooldown_seconds=300)

    for key, default in [
        ("enable_hydration_front", True),
        ("enable_drink_detection_front", True),
        ("hydrate_interval_min_front", 45),
        ("last_drink_ts_front", None),
        ("hydration_alert_sent_front", False),
        ("has_drink_event_front", False),
        ("drink_state_front", "far"),
        ("near_time_front", 0.0),
    ]:
        st.session_state.setdefault(key, default)

    # ===== NUEVO: Tiempo sentado =====
    for key, default in [
        ("enable_sitting_tracker", True),
        ("sitting_time_threshold_min", 30),  # Alert after 30 minutes
        ("sitting_start_time", None),  # When user started sitting
        ("total_sitting_time", 0.0),  # Accumulated sitting time in seconds
        ("is_currently_sitting", False),
        ("sitting_alert_sent", False),
        ("last_sitting_alert_time", 0.0),
    ]:
        if key not in st.session_state:
            st.session_state[key] = default

def render_sidebar():
    init_session_defaults()

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

        st.subheader("💧 Hidratación (Frontal)")
        st.session_state.enable_hydration_front = st.checkbox(
            "Activar hidratación (frontal)",
            value=st.session_state.enable_hydration_front
        )
        st.session_state.hydrate_interval_min_front = st.slider(
            "Intervalo (min)",
            2, 120,
            int(st.session_state.hydrate_interval_min_front),
            5
        )
        st.session_state.enable_drink_detection_front = st.checkbox(
            "Detectar gesto de beber (beta)",
            value=st.session_state.enable_drink_detection_front
        )

        if st.button("Tomé agua ✅ (manual)", key="drink_btn_sidebar_front"):
            st.session_state.last_drink_ts_front = time.time()
            st.session_state.has_drink_event_front = True
            st.session_state.drink_state_front = "far"
            st.session_state.near_time_front = 0.0
            st.success("Hidratación registrada (frontal).")

        # ===== Tiempo Sentado =====
        st.subheader("⏳ Tiempo Sentado")
        st.session_state.enable_sitting_tracker = st.checkbox(
            "Activar monitoreo de tiempo sentado",
            value=st.session_state.enable_sitting_tracker
        )
        st.session_state.sitting_time_threshold_min = st.slider(
            "Alerta después de (minutos)",
            5, 120,
            int(st.session_state.sitting_time_threshold_min),
            5,
            help="Tiempo máximo recomendado sentado antes de tomar un descanso"
        )
        
        # Botón para resetear el contador manualmente
        if st.button("Resetear tiempo sentado ⏳", key="reset_sitting_btn"):
            st.session_state.total_sitting_time = 0.0
            st.session_state.sitting_start_time = time.time()
            st.session_state.sitting_alert_sent = False
            st.success("Contador de tiempo sentado reseteado.")

    thr = {
        "FRONTAL_GOOD_MIN": float(fr_good),
        "FRONTAL_FAIR_MIN": float(fr_fair),
        "LATERAL_GOOD_MIN": float(lat_good),
        "LATERAL_FAIR_MIN": float(lat_fair),
    }

    return dict(
        lighting_thresh=float(lighting_thresh),
        process_every_n=int(process_every_n),
        debug_overlay=bool(debug_overlay),
        thr=thr,
        enable_posture_alerts=bool(enable_posture_alerts),
        posture_seconds=int(posture_seconds),
        good_seconds=int(good_seconds),
        enable_light_alerts=bool(enable_light_alerts),
        light_seconds=int(light_seconds),
        good_light_seconds=int(good_light_seconds),
        cooldown_seconds=int(cooldown_seconds),
        enable_desktop_notifications=bool(enable_desktop_notifications),
        enable_notification_sound=bool(enable_notification_sound),
    )
