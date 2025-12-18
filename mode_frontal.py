import time
import threading
import streamlit as st
from streamlit_webrtc import webrtc_streamer, WebRtcMode
from notificaciones import get_notification_message
from common import RTC_CONFIGURATION, EMA, new_shared_state, reset_shared, make_callback, posture_category_for_panel, lighting_category, update_sitting_time

def render_frontal(*, POSE, cfg):
    shared_lock = threading.Lock()
    shared = new_shared_state()
    neck_ema = EMA(alpha=0.35, initial=None)
    bright_ema = EMA(alpha=0.25, initial=60.0)
    frame_count = {"n": 0}

    colV, colS = st.columns([2, 1])

    with colV:
        st.subheader("Cámara Frontal")

        cb = make_callback(
            mode="front",
            shared=shared,
            lock=shared_lock,
            frame_counter=frame_count,
            neck_ema_obj=neck_ema,
            bright_ema_obj=bright_ema,
            POSE=POSE,
            thr=cfg["thr"],
            lighting_thresh=cfg["lighting_thresh"],
            process_every_n=cfg["process_every_n"],
            debug_overlay=cfg["debug_overlay"],
        )

        webrtc_ctx = webrtc_streamer(
            key="posture-light-front",
            mode=WebRtcMode.SENDRECV,
            rtc_configuration=RTC_CONFIGURATION,
            video_frame_callback=cb,
            media_stream_constraints={"video": {"width": 640, "height": 360, "frameRate": 15}, "audio": False},
            async_processing=True,
        )

        if webrtc_ctx.state.playing and not st.session_state.front_reset_done:
            reset_shared(shared, neck_ema, bright_ema)

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

            # Updated: Initialize hydration timestamp as None instead of time.time()
            st.session_state.last_drink_ts_front = None
            st.session_state.has_drink_event_front = False
            st.session_state.drink_state_front = "far"
            st.session_state.near_time_front = 0.0
            # New: Add hydration alert flag
            st.session_state.hydration_alert_sent_front = False

            st.session_state.front_reset_done = True
        elif not webrtc_ctx.state.playing and st.session_state.front_reset_done:
            st.session_state.front_reset_done = False

    with colS:
        st.subheader("Estado")
        panel = st.empty()
        alert_posture = st.empty()
        alert_light = st.empty()

        if webrtc_ctx.state.playing:
            while webrtc_ctx.state.playing:
                with shared_lock:
                    nang = shared["neck_angle_smooth"]
                    nraw = shared["neck_angle_raw"]
                    bsmo = shared["brightness_smooth"]
                    wd = shared.get("wrist_mouth_dist", None)

                with panel.container():
                    st.markdown("### Postura")
                    ang_now = nang if nang is not None else nraw
                    p_label, p_level, _ = posture_category_for_panel(ang_now, "front", cfg["thr"])
                    if p_level == "good": st.success(p_label)
                    elif p_level == "regular": st.warning(p_label)
                    elif p_level == "bad": st.error(p_label)
                    else: st.info(p_label)

                    if ang_now is not None: st.write(f"Ángulo del cuello: **{ang_now:.1f}°**")
                    else: st.write("Esperando detección…")

                    st.markdown("### 💡 Iluminación")
                    label, level = lighting_category(bsmo, cfg["lighting_thresh"])
                    if level == "good": st.success(label)
                    elif level == "regular": st.warning(label)
                    elif level == "bad": st.error(label)
                    else: st.info(label)
                    st.caption(f"Mínimo umbral: {cfg['lighting_thresh']:.0f} (Buena ≥ {cfg['lighting_thresh'] + 15:.0f})")

                    now = time.time()
                    dt_raw = now - st.session_state.last_tick_front
                    dt = min(max(dt_raw, 0.0), 0.5)
                    st.session_state.last_tick_front = now

                    update_sitting_time(dt, nang is not None or nraw is not None)

                    # ---- Tiempo Sentado ----
                    if st.session_state.enable_sitting_tracker:
                        st.markdown("### ⏳ Tiempo Sentado")
                        
                        # Detectar si hay pose (persona presente)
                        pose_detected = (nang is not None or nraw is not None)
                        update_sitting_time(dt, pose_detected)
                        
                        sitting_minutes = st.session_state.total_sitting_time / 60.0
                        threshold_min = st.session_state.sitting_time_threshold_min
                        
                        if st.session_state.is_currently_sitting:
                            if sitting_minutes >= threshold_min:
                                st.error(f"⚠️ Llevas {sitting_minutes:.0f} minutos sentado")
                                st.caption(f"Recomendación: Levántate cada {threshold_min} min")
                            elif sitting_minutes >= threshold_min * 0.8:
                                st.warning(f"Tiempo sentado: {sitting_minutes:.0f} min de {threshold_min}")
                            else:
                                st.info(f"Tiempo sentado: {sitting_minutes:.0f} min de {threshold_min}")
                            
                            # Enviar alerta si excede el umbral
                            if sitting_minutes >= threshold_min and not st.session_state.sitting_alert_sent:
                                if cfg["enable_desktop_notifications"]:
                                    msg = get_notification_message('sitting_too_long')
                                    success = st.session_state.notification_manager.send(
                                        'sitting_too_long',
                                        msg['title'],
                                        msg['message'],
                                        sound_type=msg['sound'],
                                        play_sound=cfg["enable_notification_sound"]
                                    )
                                    if success:
                                        st.session_state.sitting_alert_sent = True
                                        st.session_state.last_sitting_alert_time = now
                        else:
                            st.success("✅ No estás sentado o sin detección")
                            st.caption("El contador se reinicia al detectar que te levantas")                   

                    if cfg["enable_posture_alerts"]:
                        if p_level == "bad":
                            st.session_state.bad_timer_front += dt
                            st.session_state.good_timer_front = max(0.0, st.session_state.good_timer_front - dt * 0.5)
                        elif p_level == "good":
                            st.session_state.good_timer_front += dt
                            st.session_state.bad_timer_front = max(0.0, st.session_state.bad_timer_front - dt * 0.5)
                        else:
                            st.session_state.bad_timer_front = max(0.0, st.session_state.bad_timer_front - dt * 0.3)
                            st.session_state.good_timer_front = max(0.0, st.session_state.good_timer_front - dt * 0.3)

                        if (st.session_state.bad_timer_front >= cfg["posture_seconds"]) and (now >= st.session_state.bad_cool_front) and (not st.session_state.posture_alert_active_front):
                            alert_posture.error("⚠️ Mala postura mantenida. Endereza cuello y la espalda.")
                            st.session_state.posture_alert_active_front = True
                            st.session_state.bad_timer_front = 0.0
                            st.session_state.bad_cool_front = now + cfg["cooldown_seconds"]

                            if cfg["enable_desktop_notifications"]:
                                msg = get_notification_message('posture_bad_front')
                                st.session_state.notification_manager.send('posture_bad_front', msg['title'], msg['message'],
                                                                          sound_type=msg['sound'], play_sound=cfg["enable_notification_sound"])

                        if st.session_state.posture_alert_active_front and (p_level == "good") and (st.session_state.good_timer_front >= cfg["good_seconds"]):
                            alert_posture.empty()
                            st.session_state.posture_alert_active_front = False

                    if cfg["enable_light_alerts"]:
                        if level == "bad":
                            st.session_state.lowlight_timer_front += dt
                            st.session_state.goodlight_timer_front = max(0.0, st.session_state.goodlight_timer_front - dt * 0.5)
                        elif level == "good":
                            st.session_state.goodlight_timer_front += dt
                            st.session_state.lowlight_timer_front = max(0.0, st.session_state.lowlight_timer_front - dt * 0.5)
                        else:
                            st.session_state.lowlight_timer_front = max(0.0, st.session_state.lowlight_timer_front - dt * 0.3)
                            st.session_state.goodlight_timer_front = max(0.0, st.session_state.goodlight_timer_front - dt * 0.3)

                        if (st.session_state.lowlight_timer_front >= cfg["light_seconds"]) and (now >= st.session_state.lowlight_cool_front) and (not st.session_state.light_alert_active_front):
                            alert_light.warning("💡 Iluminación insuficiente. Aumenta el nivel de luz en la habitación o ajusta el umbral.")
                            st.session_state.light_alert_active_front = True
                            st.session_state.lowlight_timer_front = 0.0
                            st.session_state.lowlight_cool_front = now + cfg["cooldown_seconds"]

                            if cfg["enable_desktop_notifications"]:
                                msg = get_notification_message('lighting_low_front')
                                st.session_state.notification_manager.send('lighting_low_front', msg['title'], msg['message'],
                                                                          sound_type=msg['sound'], play_sound=cfg["enable_notification_sound"])

                        if st.session_state.light_alert_active_front and (level == "good") and (st.session_state.goodlight_timer_front >= cfg["good_light_seconds"]):
                            alert_light.empty()
                            st.session_state.light_alert_active_front = False

                    # ---- IMPROVED HYDRATION SECTION ----
                    st.markdown("### 💧 Hidratación (Frontal)")
                    if st.session_state.enable_hydration_front:
                        interval_min = float(st.session_state.hydrate_interval_min_front)

                        # Ensure hydration alert flag exists
                        if "hydration_alert_sent_front" not in st.session_state:
                            st.session_state.hydration_alert_sent_front = False

                        # ---------------------------
                        # 1) Drink Detection Logic (IMPROVED)
                        # ---------------------------
                        if st.session_state.enable_drink_detection_front and (wd is not None):
                            # Updated parameters: more conservative to reduce false positives
                            D_NEAR, D_FAR = 0.22, 0.45
                            T_MIN, T_MAX, T_FACE = 1.3, 3.0, 4.0
                            state = st.session_state.drink_state_front

                            if state == "far" and wd < D_NEAR:
                                st.session_state.drink_state_front = "near"
                                st.session_state.near_time_front = 0.0

                            elif state == "near":
                                # IMPROVED: Only accumulate time when hand is actually near
                                if wd < D_NEAR:
                                    st.session_state.near_time_front += dt

                                    # Cancel if hand stays too long (face resting on hand, etc.)
                                    if st.session_state.near_time_front > T_FACE:
                                        st.session_state.drink_state_front = "far"
                                        st.session_state.near_time_front = 0.0

                                else:
                                    # Hand moved away → evaluate gesture
                                    t = st.session_state.near_time_front

                                    # Anti-false-positive filter: minimum 60 seconds between detections
                                    MIN_GAP_SEC = 60  # 1 minute
                                    last = st.session_state.last_drink_ts_front

                                    if (t >= T_MIN) and (t <= T_MAX):
                                        if (last is None) or ((now - last) >= MIN_GAP_SEC):
                                            st.session_state.last_drink_ts_front = now
                                            st.session_state.has_drink_event_front = True

                                            # Reset alert flag - allow future notifications
                                            st.session_state.hydration_alert_sent_front = False

                                    st.session_state.drink_state_front = "far"
                                    st.session_state.near_time_front = 0.0

                        # ------------------------------------------
                        # 2) Automatic Notification when interval expires
                        #    (only once until next drink detection)
                        # ------------------------------------------
                        if (
                            cfg.get("enable_desktop_notifications", True)
                            and (st.session_state.last_drink_ts_front is not None)
                        ):
                            elapsed_min = (now - st.session_state.last_drink_ts_front) / 60.0

                            if (elapsed_min >= interval_min) and (not st.session_state.hydration_alert_sent_front):
                                # Send notification using existing system
                                try:
                                    msg = get_notification_message('hydration_reminder')
                                    st.session_state.notification_manager.send(
                                        'hydration_reminder',
                                        msg['title'],
                                        msg['message'],
                                        sound_type=msg.get('sound', 'default'),
                                        play_sound=cfg.get("enable_notification_sound", True),
                                    )
                                except Exception:
                                    # Fallback if 'hydration_reminder' key doesn't exist
                                    st.session_state.notification_manager.send(
                                        'hydration_reminder',
                                        "💧 Hora de hidratarse",
                                        "Ha pasado mucho tiempo desde tu última hidratación. Toma agua 💦",
                                        sound_type='default',
                                        play_sound=cfg.get("enable_notification_sound", True),
                                    )

                                st.session_state.hydration_alert_sent_front = True

                        # ---------------------------
                        # 3) UI Display (IMPROVED)
                        # ---------------------------
                        if st.session_state.last_drink_ts_front is None:
                            st.info(
                                f"💧 Hidratación: **sin registro aún** (intervalo: {interval_min:.0f} min).\n\n"
                                "Toma agua normalmente o usa el botón **Tomé agua ✅** una sola vez para iniciar."
                            )
                        else:
                            elapsed_min = max(0.0, (now - st.session_state.last_drink_ts_front) / 60.0)
                            
                            if elapsed_min >= interval_min:
                                st.error(f"⚠️ **Hidratación detectada hace:** {elapsed_min:.0f} min (intervalo: {interval_min:.0f} min)")
                                st.caption("¡Es hora de tomar agua!")
                            elif elapsed_min >= interval_min * 0.8:
                                st.warning(f"**Hidratación detectada hace:** {elapsed_min:.0f} min (intervalo: {interval_min:.0f} min)")
                            else:
                                st.success(f"**Hidratación detectada hace:** {elapsed_min:.0f} min (intervalo: {interval_min:.0f} min)")

                    else:
                        st.info("Hidratación desactivada (frontal).")

                time.sleep(0.25)
        else:
            st.info("Inicia la cámara para este modo.")