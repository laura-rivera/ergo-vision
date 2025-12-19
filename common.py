import time
import threading
import numpy as np
import cv2
import mediapipe as mp
import av
import streamlit as st
from streamlit_webrtc import RTCConfiguration

# =========================
# MediaPipe
# =========================
mp_pose = mp.solutions.pose
mp_drawing = mp.solutions.drawing_utils

# =========================
# WebRTC Configuration
# =========================
RTC_CONFIGURATION = RTCConfiguration({"iceServers": [{"urls": ["stun:stun.l.google.com:19302"]}]})

def try_limit_opencv_threads(n=2):
    try:
        cv2.setNumThreads(int(n))
    except Exception:
        pass

# =========================
# EMA (Exponential Moving Average)
# =========================
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

# =========================
# Geometría - Angle Calculations
# =========================
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

pose_lock = threading.Lock()

# =========================
# MediaPipe Pose Model
# =========================
def build_pose_model():
    return mp_pose.Pose(
        static_image_mode=False,
        model_complexity=1,
        enable_segmentation=False,
        min_detection_confidence=0.5,
        min_tracking_confidence=0.5,
    )

# =========================
# Shared State Management
# =========================
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
        "wrist_mouth_dist": None,  # SOLO distancia 2D
    }

def reset_shared(shared, neck_ema_obj, bright_ema_obj):
    shared.update(new_shared_state())
    neck_ema_obj.value = None
    bright_ema_obj.value = 60.0

# =========================
# Neck Angle Calculations
# =========================
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

# =========================
# Posture Classification
# =========================
def classify_posture_by_mode(angle_s, mode, thr):
    if angle_s is None:
        return "No se detecta postura", "⚪"
    
    # Soporte para ambos formatos
    if "FRONTAL_GOOD_MIN" in thr:
        # Formato antiguo
        if mode == "front":
            if angle_s >= thr["FRONTAL_GOOD_MIN"]:
                return "Buena postura", "🟢"
            if angle_s >= thr["FRONTAL_FAIR_MIN"]:
                return "Postura regular", "🟡"
            return "MALA POSTURA", "🔴"
        else:
            if angle_s >= thr["LATERAL_GOOD_MIN"]:
                return "Buena postura", "🟢"
            if angle_s >= thr["LATERAL_FAIR_MIN"]:
                return "Postura regular", "🟡"
            return "MALA POSTURA", "🔴"
    else:
        # Formato nuevo
        mode_key = "front" if mode == "front" else "side"
        if angle_s >= thr[mode_key]["good"]:
            return "Buena postura", "🟢"
        if angle_s >= thr[mode_key]["fair"]:
            return "Postura regular", "🟡"
        return "MALA POSTURA", "🔴"

def posture_category_for_panel(angle_value, mode, thr):
    # Soporte para ambos formatos
    if "FRONTAL_GOOD_MIN" in thr:
        # Formato antiguo
        if angle_value is None:
            good_thr = thr["FRONTAL_GOOD_MIN"] if mode == "front" else thr["LATERAL_GOOD_MIN"]
            return ("Sin datos de postura", "none", good_thr)

        if mode == "front":
            good_thr = thr["FRONTAL_GOOD_MIN"]
            if angle_value >= thr["FRONTAL_GOOD_MIN"]:
                return ("Buena postura", "good", good_thr)
            if angle_value >= thr["FRONTAL_FAIR_MIN"]:
                return ("Postura regular", "regular", good_thr)
            return ("MALA POSTURA", "bad", good_thr)
        else:
            good_thr = thr["LATERAL_GOOD_MIN"]
            if angle_value >= thr["LATERAL_GOOD_MIN"]:
                return ("Buena postura", "good", good_thr)
            if angle_value >= thr["LATERAL_FAIR_MIN"]:
                return ("Postura regular", "regular", good_thr)
            return ("MALA POSTURA", "bad", good_thr)
    else:
        # Formato nuevo
        mode_key = "front" if mode == "front" else "side"
        
        if angle_value is None:
            good_thr = thr[mode_key]["good"]
            return ("Sin datos de postura", "none", good_thr)

        good_thr = thr[mode_key]["good"]
        if angle_value >= thr[mode_key]["good"]:
            return ("Buena postura", "good", good_thr)
        if angle_value >= thr[mode_key]["fair"]:
            return ("Postura regular", "regular", good_thr)
        return ("MALA POSTURA", "bad", good_thr)

# =========================
# Lighting Classification
# =========================
def lighting_category(bright_smooth, thr_lighting):
    if bright_smooth is None:
        return ("Sin datos de luz", "none")
    good_min = thr_lighting + 15
    if bright_smooth < thr_lighting:
        return (f"Mala iluminación ({bright_smooth:.1f}/255)", "bad")
    elif bright_smooth < good_min:
        return (f"Iluminación regular ({bright_smooth:.1f}/255)", "regular")
    else:
        return (f"Buena iluminación ({bright_smooth:.1f}/255)", "good")

# =========================
# Frame Analysis
# =========================
def analyze(img_bgr, POSE, angle_fn, neck_ema_obj, bright_ema_obj, mode_label, thr, lighting_thresh, compute_wrist_mouth=False):
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
    posture_msg, posture_icon = classify_posture_by_mode(neck_s, mode_label, thr)

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

ORANGE = (0, 140, 255)

# =========================
# WebRTC Callback
# =========================
def make_callback(*, mode, shared, lock, frame_counter, neck_ema_obj, bright_ema_obj, POSE, thr, lighting_thresh, process_every_n, debug_overlay):
    if mode == "side":
        angle_fn = neck_angle_side_best
        title_msg = "Modo lateral"
        mode_label = "side"
        compute_wrist_mouth = True  # CHANGED: Now True for both modes
    else:
        angle_fn = neck_angle_front_best
        title_msg = "Modo frontal"
        mode_label = "front"
        compute_wrist_mouth = True

    def callback(frame: av.VideoFrame):
        img = frame.to_ndarray(format="bgr24")
        frame_counter["n"] += 1
        should_process = (frame_counter["n"] % int(process_every_n) == 0)

        if should_process:
            res, data = analyze(
                img_bgr=img,
                POSE=POSE,
                angle_fn=angle_fn,
                neck_ema_obj=neck_ema_obj,
                bright_ema_obj=bright_ema_obj,
                mode_label=mode_label,
                thr=thr,
                lighting_thresh=lighting_thresh,
                compute_wrist_mouth=compute_wrist_mouth,
            )

            if debug_overlay and res.pose_landmarks:
                mp_drawing.draw_landmarks(
                    img, res.pose_landmarks, mp_pose.POSE_CONNECTIONS,
                    mp_drawing.DrawingSpec(color=(0, 255, 0), thickness=2),
                    mp_drawing.DrawingSpec(color=(0, 0, 255), thickness=2),
                )

            with lock:
                shared.update(data)
                shared["last_update_ts"] = time.time()

            return av.VideoFrame.from_ndarray(img, format="bgr24")
        else:
            return av.VideoFrame.from_ndarray(img, format="bgr24")

    return callback

# =========================
# Sitting Time Tracker
# =========================
def update_sitting_time(dt, pose_detected):
    """
    Actualiza el tiempo sentado basándose en si se detecta pose.
    Si hay pose = persona presente = sentado
    """
    if not st.session_state.get("enable_sitting_tracker", True):
        return
    
    now = time.time()
    
    # Si detectamos pose, la persona está sentada
    if pose_detected:
        if not st.session_state.get("is_currently_sitting", False):
            # Persona acaba de sentarse
            st.session_state.is_currently_sitting = True
            st.session_state.sitting_start_time = now
        
        # Acumular tiempo sentado
        st.session_state.total_sitting_time = st.session_state.get("total_sitting_time", 0.0) + dt
        
    else:
        # No hay pose = persona no está o se levantó
        if st.session_state.get("is_currently_sitting", False):
            # Persona se levantó - resetear
            st.session_state.is_currently_sitting = False
            st.session_state.sitting_start_time = None
            st.session_state.total_sitting_time = 0.0
            st.session_state.sitting_alert_sent = False