import streamlit as st, json, io
from lib.geoutils import load_orchards, add_orchard, delete_orchard, rename_orchard, parse_polygon_from_output

st.title("🗺️ Fields (Polygons) Manager")

try:
    from streamlit_folium import st_folium
    import folium
    from folium.plugins import Draw
    center = st.session_state.get("picked_latlon", [40.916, 38.387])
    m = folium.Map(location=center, zoom_start=12, tiles="OpenStreetMap")
    Draw(export=True).add_to(m)
    out = st_folium(m, height=420, use_container_width=True)
    geom = parse_polygon_from_output(out)
    name = st.text_input("Name")
    if st.button("Save field") and geom and name:
        add_orchard(name, geom); st.success("Saved")
except Exception as e:
    st.error(str(e))

st.subheader("Saved fields")
data = load_orchards()
if data:
    sel = st.selectbox("Field", list(data.keys()))
    st.json(data[sel])
    new = st.text_input("Rename", value=sel)
    if st.button("Rename"): rename_orchard(sel, new); st.success("Renamed")
    if st.button("Delete"): delete_orchard(sel); st.warning("Deleted")
else:
    st.info("No fields yet.")
