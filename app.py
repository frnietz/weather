import streamlit as st

st.set_page_config(page_title="Letta Agritech", page_icon="🌤️", layout="wide")

st.title("Letta Agritech Platform")
st.write("Welcome! Use the navigation to explore weather, fields, satellite analytics, and models.")

st.subheader("Quick links")
try:
    st.page_link("pages/1_Weather_&_Forecast.py", label="Weather & Forecast", icon="🌦️")
    st.page_link("pages/2_Fields_Manager.py", label="Fields (Polygons) Manager", icon="🗺️")
    st.page_link("pages/3_Satellite_&_Crop_Analysis.py", label="Satellite & Crop Analysis", icon="🛰️")
    st.page_link("pages/4_Models_&_Alerts.py", label="Models & Alerts (GDD)", icon="📈")
except Exception:
    st.info("Use the sidebar page menu to navigate.")

# Initialize shared state
st.session_state.setdefault("picked_latlon", [40.916, 38.387])  # Giresun-ish default
st.session_state.setdefault("orchard_geom", None)
st.session_state.setdefault("sampled_points", None)

st.markdown("---")
st.caption("Multi‑page app. Weather powered by Open‑Meteo; maps via folium; optional NDVI via Google Earth Engine.")
