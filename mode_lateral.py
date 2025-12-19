import time
import threading
import streamlit as st
from streamlit_webrtc import webrtc_streamer, WebRtcMode
from notificaciones import get_notification_message
from common import RTC_CONFIGURATION, EMA, new_shared_state, reset_shared, make_callback, posture_category_for_panel, lighting_category, update_sitting_time
from session_logger import save_session

def _finalize_and_save_session(session_key: str, *, mode: str, cfg):
    sess = st.session_state.get(session_key)
    if not sess:
        return

    end_ts = time.time()
    sess["end_ts"] = float(end_ts)

    # derive scores (ignore none)
    posture_total = sess["posture_good_sec"] + sess["posture_regular_sec"] + sess["posture_bad_sec"]
    if posture_total > 0:
        sess["posture_score_0_100"] = 100.0 * (sess["posture_good_sec"] + 0.6 * sess["posture_regular_sec"]) / posture_total
    else:
        sess["posture_score_0_100"] = None

    light_total = sess["light_good_sec"] + sess["light_regular_sec"] + sess["light_bad_sec"]
    if light_total > 0:
        sess["light_score_0_100"] = 100.0 * (sess["light_good_sec"] + 0.6 * sess["light_regular_sec"]) / light_total
    else:
        sess["light_score_0_100"] = None

    # hydration intervals
    ts = sorted(set([float(t) for t in sess.get("drink_events_ts", [])]))
    sess["drink_events_count"] = int(len(ts))
    if len(ts) >= 2:
        gaps = [(ts[i] - ts[i-1]) / 60.0 for i in range(1, len(ts))]
        sess["avg_minutes_between_drinks"] = float(sum(gaps) / len(gaps))
    else:
        sess["avg_minutes_between_drinks"] = None

    row = {
        "start_ts": float(sess["start_ts"]),
        "end_ts": float(sess["end_ts"]),
        "mode": mode,
        "duration_sec": float(sess["duration_sec"]),

        "posture_good_sec": float(sess["posture_good_sec"]),
        "posture_regular_sec": float(sess["posture_regular_sec"]),
        "posture_bad_sec": float(sess["posture_bad_sec"]),
        "posture_none_sec": float(sess["posture_none_sec"]),
        "posture_alerts_count": int(sess["posture_alerts_count"]),
        "posture_bad_streak_max_sec": float(sess["posture_bad_streak_max_sec"]),
        "posture_score_0_100": sess["posture_score_0_100"],

        "light_good_sec": float(sess["light_good_sec"]),
        "light_regular_sec": float(sess["light_regular_sec"]),
        "light_bad_sec": float(sess["light_bad_sec"]),
        "light_none_sec": float(sess["light_none_sec"]),
        "light_alerts_count": int(sess["light_alerts_count"]),
        "light_bad_streak_max_sec": float(sess["light_bad_streak_max_sec"]),
        "light_score_0_100": sess["light_score_0_100"],

        "drink_events_count": int(sess["drink_events_count"]),
        "hydration_reminders_sent_count": int(sess["hydration_reminders_sent_count"]),
        "avg_minutes_between_drinks": sess["avg_minutes_between_drinks"],
    }
    # Keep full metrics in metrics_json
    row.update({
        "metrics": {
            "drink_events_ts": ts,
            "posture_bad_streak_cur_sec": sess.get("posture_bad_streak_cur_sec", 0.0),
            "light_bad_streak_cur_sec": sess.get("light_bad_streak_cur_sec", 0.0),
        }
    })

    if cfg.get("enable_history", True):
        db_path = cfg.get("history_db_path", "ergovision_sessions.db")
        save_session(row, db_path=db_path)

    # cleanup
    try:
        del st.session_state[session_key]
    except Exception:
        st.session_state[session_key] = None

def render_lateral(*, POSE, cfg):
    shared_lock = threading.Lock()
    shared = new_shared_state()
    neck_ema = EMA(alpha=0.35, initial=None)
    bright_ema = EMA(alpha=0.25, initial=60.0)
    frame_count = {"n": 0}

    colV, colS = st.columns([2, 1])

    with colV:
        st.subheader("Cámara Lateral")

        cb = make_callback(
            mode="side",
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
            key="posture-light-side",
            mode=WebRtcMode.SENDRECV,
            rtc_configuration=RTC_CONFIGURATION,
            video_frame_callback=cb,
            media_stream_constraints={"video": {"width": 640, "height": 360, "frameRate": 15}, "audio": False},
            async_processing=True,
        )
        

        if webrtc_ctx.state.playing and not st.session_state.side_reset_done:
            reset_shared(shared, neck_ema, bright_ema)
            now = time.time()
            st.session_state.last_tick_side = now
            
            # NUEVO: Reset de hidratación por sesión
            st.session_state.last_drink_ts = None
            st.session_state.has_drink_event = False
            st.session_state.hydration_alert_sent = False
            st.session_state.drink_state = "far"
            st.session_state.near_time = 0.0
            
            # NUEVO: Inicializar sesión para historial
            if cfg.get("enable_history", True):
                st.session_state["active_session_side"] = {
                    "start_ts": float(now),
                    "duration_sec": 0.0,
                    "posture_good_sec": 0.0,
                    "posture_regular_sec": 0.0,
                    "posture_bad_sec": 0.0,
                    "posture_none_sec": 0.0,
                    "posture_alerts_count": 0,
                    "posture_bad_streak_cur_sec": 0.0,
                    "posture_bad_streak_max_sec": 0.0,
                    "light_good_sec": 0.0,
                    "light_regular_sec": 0.0,
                    "light_bad_sec": 0.0,
                    "light_none_sec": 0.0,
                    "light_alerts_count": 0,
                    "light_bad_streak_cur_sec": 0.0,
                    "light_bad_streak_max_sec": 0.0,
                    "drink_events_ts": [],
                    "last_drink_ts_seen": None,
                    "hydration_reminders_sent_count": 0,
                }
            
            # Inicialización del sistema de hidratación compartido
            if "hydration_alert_sent_front" not in st.session_state:
                st.session_state.hydration_alert_sent_front = False
            if "hydration_alert_sent_side" not in st.session_state:
                st.session_state.hydration_alert_sent_side = False
            # Marcar que la alerta fue enviada para ambos modos
            st.session_state.hydration_alert_sent = False
            
            st.session_state.side_reset_done = True

        elif not webrtc_ctx.state.playing and st.session_state.side_reset_done:
            # NUEVO: Guardar sesión al detener
            _finalize_and_save_session("active_session_side", mode="side", cfg=cfg)
            st.session_state.side_reset_done = False

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
                    p_label, p_level, _ = posture_category_for_panel(ang_now, "side", cfg["thr"])
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
                    dt_raw = now - st.session_state.last_tick_side
                    dt = min(max(dt_raw, 0.0), 0.5)
                    st.session_state.last_tick_side = now

                    update_sitting_time(dt, nang is not None or nraw is not None)

                    # ===== NUEVO: ACUMULAR MÉTRICAS PARA HISTORIAL =====
                    sess = st.session_state.get("active_session_side")
                    if sess is not None:
                        sess["duration_sec"] += dt
                        
                        # Acumular postura
                        if p_level == "good":
                            sess["posture_good_sec"] += dt
                            sess["posture_bad_streak_cur_sec"] = max(0.0, sess["posture_bad_streak_cur_sec"] - dt * 0.5)
                        elif p_level == "regular":
                            sess["posture_regular_sec"] += dt
                            sess["posture_bad_streak_cur_sec"] = max(0.0, sess["posture_bad_streak_cur_sec"] - dt * 0.3)
                        elif p_level == "bad":
                            sess["posture_bad_sec"] += dt
                            sess["posture_bad_streak_cur_sec"] += dt
                            if sess["posture_bad_streak_cur_sec"] > sess["posture_bad_streak_max_sec"]:
                                sess["posture_bad_streak_max_sec"] = sess["posture_bad_streak_cur_sec"]
                        else:
                            sess["posture_none_sec"] += dt
                        
                        # Acumular luz
                        if level == "good":
                            sess["light_good_sec"] += dt
                            sess["light_bad_streak_cur_sec"] = max(0.0, sess["light_bad_streak_cur_sec"] - dt * 0.5)
                        elif level == "regular":
                            sess["light_regular_sec"] += dt
                            sess["light_bad_streak_cur_sec"] = max(0.0, sess["light_bad_streak_cur_sec"] - dt * 0.3)
                        elif level == "bad":
                            sess["light_bad_sec"] += dt
                            sess["light_bad_streak_cur_sec"] += dt
                            if sess["light_bad_streak_cur_sec"] > sess["light_bad_streak_max_sec"]:
                                sess["light_bad_streak_max_sec"] = sess["light_bad_streak_cur_sec"]
                        else:
                            sess["light_none_sec"] += dt
                        
                        # Capturar eventos de hidratación
                        cur_drink = st.session_state.get("last_drink_ts", None)
                        prev_seen = sess.get("last_drink_ts_seen", None)
                        if cur_drink is not None:
                            try:
                                cur_drink_f = float(cur_drink)
                                if (prev_seen is None) or (cur_drink_f > float(prev_seen) + 1e-6):
                                    if cur_drink_f >= (sess["start_ts"] - 1.0):
                                        sess["drink_events_ts"].append(cur_drink_f)
                                    sess["last_drink_ts_seen"] = cur_drink_f
                            except Exception:
                                pass
                    # ===== FIN DE NUEVA SECCIÓN =====

                    # ---- Tiempo Sentado ----
                    if st.session_state.enable_sitting_tracker:
                        st.markdown("### 🪑 Tiempo Sentado")
                        
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

                    # ---- Hidratación ----
                    if st.session_state.enable_hydration:
                        st.markdown("### 💧 Hidratación")
                        
                        interval_min = float(st.session_state.hydrate_interval_min)

                        if "hydration_alert_sent" not in st.session_state:
                            st.session_state.hydration_alert_sent = False

                        # Detección de gesto (distancia muñeca→nariz)
                        if st.session_state.enable_drink_detection and (wd is not None):
                            D_NEAR, D_FAR = 0.22, 0.45
                            T_MIN, T_MAX, T_FACE = 2.0, 3.0, 4.0
                            state = st.session_state.drink_state

                            if state == "far" and wd < D_NEAR:
                                st.session_state.drink_state = "near"
                                st.session_state.near_time = 0.0

                            elif state == "near":
                                if wd < D_NEAR:
                                    st.session_state.near_time += dt
                                    if st.session_state.near_time > T_FACE:
                                        st.session_state.drink_state = "far"
                                        st.session_state.near_time = 0.0
                                else:
                                    t = st.session_state.near_time

                                    MIN_GAP_SEC = 60
                                    last = st.session_state.last_drink_ts

                                    if (t >= T_MIN) and (t <= T_MAX):
                                        if (last is None) or ((now - last) >= MIN_GAP_SEC):
                                            st.session_state.last_drink_ts = now
                                            st.session_state.has_drink_event = True
                                            st.session_state.hydration_alert_sent = False

                                    st.session_state.drink_state = "far"
                                    st.session_state.near_time = 0.0

                        # Notificación cuando vence el intervalo
                        if cfg.get("enable_desktop_notifications", True) and (st.session_state.last_drink_ts is not None):
                            elapsed_min = (now - st.session_state.last_drink_ts) / 60.0
                            if (elapsed_min >= interval_min) and (not st.session_state.hydration_alert_sent):
                                msg = get_notification_message('hydration_reminder')
                                st.session_state.notification_manager.send(
                                    'hydration_reminder',
                                    msg['title'],
                                    msg['message'],
                                    sound_type=msg.get('sound', 'default'),
                                    play_sound=cfg.get("enable_notification_sound", True),
                                )
                                st.session_state.hydration_alert_sent = True

                                # NUEVO: Incrementar contador de recordatorios
                                sess = st.session_state.get("active_session_side")
                                if sess is not None:
                                    sess["hydration_reminders_sent_count"] += 1

                        # Estado visual
                        if st.session_state.last_drink_ts is None:
                            st.info(f"Sin registro aún (intervalo: {interval_min:.0f} min)")
                            st.caption("Toma agua o usa el botón manual para iniciar")
                        else:
                            elapsed_min = max(0.0, (now - st.session_state.last_drink_ts) / 60.0)
                            if elapsed_min >= interval_min:
                                st.error(f"⚠️ Han pasado {elapsed_min:.0f} minutos desde la última hidratación")
                                st.caption(f"Recomendación: Toma agua cada {interval_min:.0f} min")
                            elif elapsed_min >= interval_min * 0.8:
                                st.warning(f"Última hidratación: hace {elapsed_min:.0f} min (de {interval_min:.0f})")
                            else:
                                st.success(f"Última hidratación: hace {elapsed_min:.0f} min (de {interval_min:.0f})")

                    if cfg["enable_posture_alerts"]:
                        if p_level == "bad":
                            st.session_state.bad_timer_side += dt
                            st.session_state.good_timer_side = max(0.0, st.session_state.good_timer_side - dt * 0.5)
                        elif p_level == "good":
                            st.session_state.good_timer_side += dt
                            st.session_state.bad_timer_side = max(0.0, st.session_state.bad_timer_side - dt * 0.5)
                        else:
                            st.session_state.bad_timer_side = max(0.0, st.session_state.bad_timer_side - dt * 0.3)
                            st.session_state.good_timer_side = max(0.0, st.session_state.good_timer_side - dt * 0.3)

                        if (st.session_state.bad_timer_side >= cfg["posture_seconds"]) and (now >= st.session_state.bad_cool_side) and (not st.session_state.posture_alert_active_side):
                            alert_posture.error("⚠️ Mala postura mantenida. Endereza cuello y la espalda.")
                            st.session_state.postura_alert_active_side = True
                            st.session_state.bad_timer_side = 0.0
                            st.session_state.bad_cool_side = now + cfg["cooldown_seconds"]

                            if cfg["enable_desktop_notifications"]:
                                msg = get_notification_message('posture_bad_side')
                                st.session_state.notification_manager.send('posture_bad_side', msg['title'], msg['message'],
                                                                          sound_type=msg['sound'], play_sound=cfg["enable_notification_sound"])
                            # NUEVO: Incrementar contador de alertas de postura
                            sess = st.session_state.get("active_session_side")
                            if sess is not None:
                                sess["posture_alerts_count"] += 1

                        if st.session_state.posture_alert_active_side and (p_level == "good") and (st.session_state.good_timer_side >= cfg["good_seconds"]):
                            alert_posture.empty()
                            st.session_state.posture_alert_active_side = False

                    if cfg["enable_light_alerts"]:
                        if level == "bad":
                            st.session_state.lowlight_timer_side += dt
                            st.session_state.goodlight_timer_side = max(0.0, st.session_state.goodlight_timer_side - dt * 0.5)
                        elif level == "good":
                            st.session_state.goodlight_timer_side += dt
                            st.session_state.lowlight_timer_side = max(0.0, st.session_state.lowlight_timer_side - dt * 0.5)
                        else:
                            st.session_state.lowlight_timer_side = max(0.0, st.session_state.lowlight_timer_side - dt * 0.3)
                            st.session_state.goodlight_timer_side = max(0.0, st.session_state.goodlight_timer_side - dt * 0.3)

                        if (st.session_state.lowlight_timer_side >= cfg["light_seconds"]) and (now >= st.session_state.lowlight_cool_side) and (not st.session_state.light_alert_active_side):
                            alert_light.warning("💡 Iluminación insuficiente. Aumenta el nivel de luz en la habitación o ajusta el umbral.")
                            st.session_state.light_alert_active_side = True
                            st.session_state.lowlight_timer_side = 0.0
                            st.session_state.lowlight_cool_side = now + cfg["cooldown_seconds"]

                            if cfg["enable_desktop_notifications"]:
                                msg = get_notification_message('lighting_low_side')
                                st.session_state.notification_manager.send('lighting_low_side', msg['title'], msg['message'],
                                                                          sound_type=msg['sound'], play_sound=cfg["enable_notification_sound"])
                            # NUEVO: Incrementar contador de alertas de luz
                            sess = st.session_state.get("active_session_side")
                            if sess is not None:
                                sess["light_alerts_count"] += 1

                        if st.session_state.light_alert_active_side and (level == "good") and (st.session_state.goodlight_timer_side >= cfg["good_light_seconds"]):
                            alert_light.empty()
                            st.session_state.light_alert_active_side = False

                time.sleep(0.25)
        else:
            st.info("Inicia la cámara para este modo.")