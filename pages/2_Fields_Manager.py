import streamlit as st
import json, io
from lib.geoutils import load_orchards, save_orchards, add_orchard, delete_orchard, rename_orchard, parse_polygon_from_output

st.title("🗺️ Fields (Polygons) Manager")

cols = st.columns([1.2, 0.8])
with cols[0]:
    st.subheader("Draw a new field")
    try:
        from streamlit_folium import st_folium
        import folium
        from folium.plugins import Draw
        center = st.session_state.get("picked_latlon", [40.916, 38.387])
        m = folium.Map(location=center, zoom_start=12, tiles="OpenStreetMap")
        draw = Draw(export=True, position="topleft",
                    draw_options={"polyline": False, "rectangle": True, "polygon": True,
                                  "circle": False, "marker": False, "circlemarker": False},
                    edit_options={"edit": True, "remove": True})
        draw.add_to(m)
        out = st_folium(m, height=500, use_container_width=True)
        geom = parse_polygon_from_output(out)
        name = st.text_input("Name for this field", placeholder="e.g., Orchard A — North Block")
        if st.button("Save Field", type="primary") and geom and geom.get("type") == "Polygon" and name.strip():
            add_orchard(name.strip(), geom)
            st.success(f"Saved field: {name.strip()}")
    except Exception as e:
        st.error("Map component not available. Install streamlit-folium and folium.")
        st.code("pip install streamlit-folium folium")

with cols[1]:
    st.subheader("Your fields")
    data = load_orchards()
    if not data:
        st.info("No fields saved yet.")
    else:
        sel_name = st.selectbox("Select a field", options=list(data.keys()))
        if sel_name:
            st.json(data[sel_name])
            new_name = st.text_input("Rename", value=sel_name)
            if st.button("Rename"):
                if new_name and new_name != sel_name:
                    rename_orchard(sel_name, new_name)
                    st.success("Renamed. Refresh the list.")
            if st.button("Delete", type="secondary"):
                delete_orchard(sel_name)
                st.warning("Deleted. Refresh the page to update the list.")
            # Export
            buf = io.StringIO(json.dumps(data[sel_name], ensure_ascii=False, indent=2))
            st.download_button("Download GeoJSON", data=buf.getvalue(), file_name=f"{sel_name}.geojson", mime="application/geo+json")

    st.markdown("---")
    st.subheader("Import GeoJSON")
    up = st.file_uploader("Upload a Polygon GeoJSON", type=["geojson", "json"])
    if up:
        try:
            geom = json.load(up)
            # Accept either Feature or raw Polygon geometry
            if geom.get("type") == "Feature":
                geom = geom.get("geometry", {})
            gtype = geom.get("type")
            if gtype != "Polygon":
                st.error(f"Expected Polygon geometry; got {gtype}")
            else:
                name2 = st.text_input("Name for the imported field", value="Imported field")
                if st.button("Save Imported Field"):
                    add_orchard(name2, geom)
                    st.success("Imported!")
        except Exception as e:
            st.error(f"Invalid GeoJSON: {e}")
