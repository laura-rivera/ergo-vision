import datetime as _dt
import pandas as pd
import streamlit as st

from session_logger import fetch_sessions, DEFAULT_DB_PATH


def _fmt_dt(ts: float) -> str:
    try:
        return _dt.datetime.fromtimestamp(float(ts)).strftime("%Y-%m-%d %H:%M")
    except Exception:
        return "—"


def render_history(db_path: str = DEFAULT_DB_PATH, limit: int = 200):
    st.subheader("📈 Historial (sesiones)")
    rows = fetch_sessions(limit=limit, db_path=db_path)

    if not rows:
        st.info("Aún no hay sesiones registradas. Inicia una cámara (frontal o lateral) y úsala unos minutos.")
        return

    # DataFrame base
    df = pd.DataFrame(rows)

    df["Inicio"] = df["start_ts"].apply(_fmt_dt)
    df["Fin"] = df["end_ts"].apply(_fmt_dt)
    df["Duración (min)"] = (df["duration_sec"] / 60.0).round(1)

    # CONVERT ALL NUMERIC COLUMNS FIRST
    # Posture and light scores
    df["posture_score_0_100"] = pd.to_numeric(df["posture_score_0_100"], errors='coerce')
    df["light_score_0_100"] = pd.to_numeric(df["light_score_0_100"], errors='coerce')
    
    # Duration columns (these should already be numeric, but just in case)
    numeric_cols = [
        "posture_good_sec", "posture_regular_sec", "posture_bad_sec", "posture_none_sec",
        "light_good_sec", "light_regular_sec", "light_bad_sec", "light_none_sec",
        "drink_events_count", "hydration_reminders_sent_count", "avg_minutes_between_drinks"
    ]
    
    for col in numeric_cols:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors='coerce')

    # Now create the rounded columns
    df["Postura Buena %"] = df["posture_score_0_100"].round(1)
    df["Luz Buena %"] = df["light_score_0_100"].round(1)

    # Porcentaje malo
    def pct(bad, total):
        try:
            return 100.0 * float(bad) / max(float(total), 1e-9)
        except Exception:
            return 0.0

    df["Postura mala %"] = [
        pct(b, g + r + b + n)
        for b, g, r, n in zip(
            df["posture_bad_sec"],
            df["posture_good_sec"],
            df["posture_regular_sec"],
            df["posture_none_sec"],
        )
    ]

    df["Luz mala %"] = [
        pct(b, g + r + b + n)
        for b, g, r, n in zip(
            df["light_bad_sec"],
            df["light_good_sec"],
            df["light_regular_sec"],
            df["light_none_sec"],
        )
    ]

    df["Postura mala %"] = df["Postura mala %"].round(1)
    df["Luz mala %"] = df["Luz mala %"].round(1)

    # Hidratación - CONVERT THESE FIRST
    df["drink_events_count"] = pd.to_numeric(df["drink_events_count"], errors='coerce')
    df["hydration_reminders_sent_count"] = pd.to_numeric(df["hydration_reminders_sent_count"], errors='coerce')
    df["avg_minutes_between_drinks"] = pd.to_numeric(df["avg_minutes_between_drinks"], errors='coerce')
    
    df["Bebidas (eventos)"] = df["drink_events_count"].fillna(0).astype(int)
    df["Recordatorios hidratación"] = df["hydration_reminders_sent_count"].fillna(0).astype(int)
    df["Prom. min entre bebidas"] = df["avg_minutes_between_drinks"].round(1)

 
    # KPIs
    st.markdown("### Resumen rápido")
    total_minutes = float(df["duration_sec"].sum() / 60.0)

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Sesiones", str(len(df)))
    col2.metric("Tiempo monitoreado", f"{total_minutes:.1f} min")
    col3.metric("Prom. Postura", f"{df['Postura Buena %'].mean():.1f}%")
    col4.metric("Prom. Luz", f"{df['Luz Buena %'].mean():.1f}%")


    # Tendencias
    st.markdown("### Tendencia (por sesión)")
    trend = df.sort_values("end_ts")[["Postura Buena %", "Luz Buena %"]]
    st.line_chart(trend, height=220)


    # Tabla final
    st.markdown("### Detalle de sesiones")

    show_cols = [
        "Inicio",
        "Fin",
        "mode",
        "Duración (min)",
        "Postura Buena %",
        "Postura mala %",
        "posture_alerts_count",
        "Luz Buena %",
        "Luz mala %",
        "light_alerts_count",
        "Bebidas (eventos)",
        "Recordatorios hidratación",
        "Prom. min entre bebidas",
    ]

    df2 = df.copy()
    df2["mode"] = df2["mode"].replace({"front": "frontal", "side": "lateral"})

    df2 = df2[show_cols].rename(
        columns={
            "mode": "Modo",
            "posture_alerts_count": "Alertas postura",
            "light_alerts_count": "Alertas luz",
        }
    )

    df2 = df2.fillna("—")

    st.dataframe(df2, use_container_width=True, hide_index=True)

    st.caption("Nota: se guarda un resumen por sesión (no se guarda video ni frames).")

