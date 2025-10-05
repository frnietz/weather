import streamlit as st
import pandas as pd
from datetime import date
from lib.geoutils import load_orchards
st.title("🛰️ Satellite & Crop Analysis")

left, right = st.columns([1.1, 0.9], vertical_alignment="top")

with left:
    st.subheader("Basemap & Layers")
    try:
        from streamlit_folium import st_folium
        import folium
        center = st.session_state.get("picked_latlon", [40.916, 38.387])
        m = folium.Map(location=center, zoom_start=12, tiles=None)
        folium.TileLayer("OpenStreetMap", name="OSM").add_to(m)
        folium.TileLayer(
            tiles="https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
            attr="Esri World Imagery", name="Esri World Imagery", overlay=False, control=True
        ).add_to(m)

        # Show saved orchards as overlays
        orch = load_orchards()
        if orch:
            for name, geom in orch.items():
                gj = folium.GeoJson(geom, name=name, tooltip=name)
                gj.add_to(m)
        folium.LayerControl(collapsed=False).add_to(m)

        st_folium(m, height=520, use_container_width=True, key="sat_map")
        st.caption("Tip: save your fields in the Fields Manager. They appear here as overlays.")
    except Exception as e:
        st.error("Map component not available. Install streamlit-folium and folium.")
        st.code("pip install streamlit-folium folium")

with right:
    st.subheader("NDVI Time Series (Pro — Earth Engine)")
    st.write("Compute NDVI statistics over a selected orchard (MODIS 16‑day composites).")

    orch = load_orchards()
    if not orch:
        st.info("No saved fields. Go to the Fields Manager page to add one.")
    else:
        names = list(orch.keys())
        field = st.selectbox("Field", names)
        start = st.date_input("Start", value=date(date.today().year, 4, 1))
        end = st.date_input("End", value=date(date.today().year, 9, 30))
        ndvi_thresh = st.slider("NDVI 'healthy canopy' threshold", 0.2, 0.9, 0.6, 0.05)
        run = st.button("Run NDVI Analysis")

        if run:
            geom = orch[field]
            try:
                import ee, json
                try:
                    ee.Initialize()
                except Exception as init_err:
                    import os, json
                    sa = os.getenv("EE_SERVICE_ACCOUNT")
                    key_json = os.getenv("EE_PRIVATE_KEY_JSON")
                    if sa and key_json:
                        creds = ee.ServiceAccountCredentials(sa, key_data=json.loads(key_json))
                        ee.Initialize(creds)
                    else:
                        raise init_err

                # Build EE polygon (expects lon/lat order)
                coords = geom["coordinates"][0]
                ee_poly = ee.Geometry.Polygon(coords)

                col = (ee.ImageCollection("MODIS/061/MOD13Q1")
                       .filterDate(str(start), str(end))
                       .filterBounds(ee_poly)
                       .select(["NDVI"]))

                def scale(img):
                    nd = img.select("NDVI").multiply(0.0001).copyProperties(img, ["system:time_start"])
                    return nd.rename("NDVI")
                col = col.map(scale)

                def stats(img):
                    mean = img.reduceRegion(ee.Reducer.mean(), ee_poly, 250).get("NDVI")
                    frac = img.gt(ndvi_thresh).reduceRegion(ee.Reducer.mean(), ee_poly, 250).get("NDVI")
                    return ee.Feature(None, {
                        "date": ee.Date(img.get("system:time_start")).format("YYYY-MM-dd"),
                        "ndvi_mean": mean,
                        "frac_above_thresh": frac
                    })

                fc = col.map(stats).filter(ee.Filter.notNull(["ndvi_mean"]))
                result = fc.getInfo()["features"]
                if not result:
                    st.warning("No NDVI data returned for the selected period/area.")
                else:
                    import pandas as pd
                    df = pd.DataFrame([f["properties"] for f in result])
                    df["date"] = pd.to_datetime(df["date"])
                    df = df.sort_values("date").set_index("date")
                    st.write("**NDVI time series (area mean)**")
                    st.line_chart(df[["ndvi_mean"]])
                    st.write("**% of area above threshold**")
                    st.line_chart(df[["frac_above_thresh"]])
            except ModuleNotFoundError:
                st.error("Earth Engine isn't installed. Run: `pip install earthengine-api geemap`")
                st.info("Then authenticate once: `earthengine authenticate`")
            except Exception as e:
                st.error(f"NDVI analysis failed: {e}")
