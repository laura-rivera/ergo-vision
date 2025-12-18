import time
import threading
import streamlit as st
from streamlit_webrtc import webrtc_streamer, WebRtcMode
from notificaciones import get_notification_message
from common import RTC_CONFIGURATION, EMA, new_shared_state, reset_shared, make_callback, posture_category_for_panel, lighting_category, update_sitting_time

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
            st.session_state.bad_timer_side = 0.0
            st.session_state.lowlight_timer_side = 0.0
            st.session_state.good_timer_side = 0.0
            st.session_state.goodlight_timer_side = 0.0
            st.session_state.posture_alert_active_side = False
            st.session_state.light_alert_active_side = False
            st.session_state.bad_cool_side = 0.0
            st.session_state.lowlight_cool_side = 0.0
            st.session_state.side_reset_done = True
        elif not webrtc_ctx.state.playing and st.session_state.side_reset_done:
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

                    # ---- Tiempo Sentado ----
                    if st.session_state.enable_sitting_tracker:
                        st.markdown("### ðŸª' Tiempo Sentado")
                        
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
                            st.session_state.posture_alert_active_side = True
                            st.session_state.bad_timer_side = 0.0
                            st.session_state.bad_cool_side = now + cfg["cooldown_seconds"]

                            if cfg["enable_desktop_notifications"]:
                                msg = get_notification_message('posture_bad_side')
                                st.session_state.notification_manager.send('posture_bad_side', msg['title'], msg['message'],
                                                                          sound_type=msg['sound'], play_sound=cfg["enable_notification_sound"])

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

                        if st.session_state.light_alert_active_side and (level == "good") and (st.session_state.goodlight_timer_side >= cfg["good_light_seconds"]):
                            alert_light.empty()
                            st.session_state.light_alert_active_side = False

                time.sleep(0.25)
        else:
            st.info("Inicia la cámara para este modo.")
