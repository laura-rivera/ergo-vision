import time
import threading
import streamlit as st
from streamlit_webrtc import webrtc_streamer, WebRtcMode
from notificaciones import get_notification_message
from common import RTC_CONFIGURATION, EMA, new_shared_state, reset_shared, make_callback, posture_category_for_panel, lighting_category

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

            st.session_state.last_drink_ts_front = time.time()
            st.session_state.has_drink_event_front = False
            st.session_state.drink_state_front = "far"
            st.session_state.near_time_front = 0.0

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

                    st.markdown("### 💧 Hidratación (Frontal)")
                    if st.session_state.enable_hydration_front:
                        interval_min = float(st.session_state.hydrate_interval_min_front)
                        if st.session_state.enable_drink_detection_front and (wd is not None):
                            D_NEAR, D_FAR = 0.09, 0.14
                            T_MIN, T_MAX, T_FACE = 0.6, 2.0, 3.5
                            state = st.session_state.drink_state_front

                            if state == "far" and wd < D_NEAR:
                                st.session_state.drink_state_front = "near"
                                st.session_state.near_time_front = 0.0
                            elif state == "near":
                                st.session_state.near_time_front += dt
                                if st.session_state.near_time_front > T_FACE:
                                    st.session_state.drink_state_front = "far"
                                    st.session_state.near_time_front = 0.0
                                if wd > D_FAR:
                                    t = st.session_state.near_time_front
                                    if (t >= T_MIN) and (t <= T_MAX):
                                        st.session_state.last_drink_ts_front = now
                                        st.session_state.has_drink_event_front = True
                                    st.session_state.drink_state_front = "far"
                                    st.session_state.near_time_front = 0.0

                        if st.session_state.has_drink_event_front:
                            elapsed_min = max(0.0, (now - st.session_state.last_drink_ts_front) / 60.0)
                            st.write(f"**Hidratación detectada hace:** {elapsed_min:.0f} min (intervalo: {interval_min:.0f} min)")
                        else:
                            st.write(f"**Hidratación:** sin detección todavía (intervalo: {interval_min:.0f} min)")
                    else:
                        st.info("Hidratación desactivada (frontal).")

                time.sleep(0.25)
        else:
            st.info("Inicia la cámara para este modo.")
