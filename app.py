import streamlit as st

st.set_page_config(page_title="Letta Agritech", page_icon="🌤️", layout="wide")
st.title("Letta Agritech Platform")
st.write("Use the sidebar pages to explore weather, fields, satellite analytics, models, alerts, and the hazelnut guide.")

try:
    st.page_link("pages/1_Weather_&_Forecast.py", label="Weather & Forecast", icon="🌦️")
    st.page_link("pages/2_Fields_Manager.py", label="Fields (Polygons) Manager", icon="🗺️")
    st.page_link("pages/3_Satellite_&_Crop_Analysis.py", label="Satellite & Crop Analysis", icon="🛰️")
    st.page_link("pages/4_Models_&_Alerts.py", label="Models & Alerts (GDD + Guide Alerts)", icon="🚨")
    st.page_link("pages/5_Hazelnut_Guide.py", label="Hazelnut Guide", icon="🌰")
except Exception:
    st.info("Use the sidebar page menu to navigate.")

st.session_state.setdefault("picked_latlon", [40.916, 38.387])
st.session_state.setdefault("orchard_geom", None)
st.session_state.setdefault("sampled_points", None)

st.markdown("---")
st.caption("Weather: Open‑Meteo • Maps: folium • NDVI (optional): Google Earth Engine")
