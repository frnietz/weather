import streamlit as st
from lib.data_sources import geocode_place, fetch_openmeteo_archive, hourly_to_dataframe, daily_to_dataframe, summarize_daily_from_hourly, add_weather_desc
from lib.geoutils import parse_polygon_from_output, polygon_bounds, sample_points_in_polygon

st.title("🌦️ Weather & Forecast (core historical)")

with st.sidebar:
    mode = st.radio("Select by:", ["Place name", "Latitude/Longitude", "Pick on Map", "Draw Area (Polygon)"])
    tz_str = "auto"
    from datetime import date, timedelta
    today = date.today()
    start_date = st.date_input("Start date", value=today - timedelta(days=30))
    end_date = st.date_input("End date", value=today)
    fetch = st.button("Fetch", type="primary")

lat = lon = None
if mode == "Place name":
    q = st.text_input("Name", "Giresun")
    results = geocode_place(q) if q else []
    if results:
        labels = [f"{r['name']}, {r.get('country','')} ({r['latitude']:.3f},{r['longitude']:.3f})" for r in results]
        idx = st.selectbox("Result", range(len(results)), format_func=lambda i: labels[i])
        if idx is not None: lat, lon = results[idx]["latitude"], results[idx]["longitude"]
elif mode == "Latitude/Longitude":
    lat = st.number_input("Lat", value=40.916, format="%.6f")
    lon = st.number_input("Lon", value=38.387, format="%.6f")

if fetch:
    if mode == "Draw Area (Polygon)":
        try:
            from streamlit_folium import st_folium
            import folium
            from folium.plugins import Draw
            center = [40.916, 38.387]
            m = folium.Map(location=center, zoom_start=12)
            Draw(export=True).add_to(m)
            out = st_folium(m, height=420, use_container_width=True)
            geom = parse_polygon_from_output(out)
            if not geom: st.warning("Draw a polygon."); st.stop()
            pts = sample_points_in_polygon(geom, max_points=9)
            st.write(f"Sampling {len(pts)} points...")
            dailies = []
            for la, lo in pts:
                hist = fetch_openmeteo_archive(la, lo, start_date.isoformat(), end_date.isoformat(), "auto")
                hdf = hourly_to_dataframe(hist)
                ddf = daily_to_dataframe(hist).rename(columns={"temperature_2m_min":"t_min_api","temperature_2m_max":"t_max_api","precipitation_sum":"precip_sum_api","wind_speed_10m_max":"wind_max_api"})
                ddf = ddf.join(summarize_daily_from_hourly(hdf), how="outer").sort_index()
                ddf = add_weather_desc(ddf)
                dailies.append(ddf)
            import pandas as pd, numpy as np
            all_idx = sorted(set().union(*[d.index for d in dailies]))
            aligned = [d.reindex(all_idx) for d in dailies]
            stacked = pd.concat(aligned, axis=1, keys=range(len(aligned)))
            daily = stacked.groupby(level=1, axis=1).mean(numeric_only=True)
            st.dataframe(daily)
        except Exception as e:
            st.error(str(e))
    else:
        if lat is None or lon is None: st.warning("Select a location first."); st.stop()
        hist = fetch_openmeteo_archive(lat, lon, start_date.isoformat(), end_date.isoformat(), "auto")
        hdf = hourly_to_dataframe(hist)
        ddf = daily_to_dataframe(hist).rename(columns={"temperature_2m_min":"t_min_api","temperature_2m_max":"t_max_api","precipitation_sum":"precip_sum_api","wind_speed_10m_max":"wind_max_api"})
        ddf = ddf.join(summarize_daily_from_hourly(hdf), how="outer").sort_index()
        ddf = add_weather_desc(ddf)
        st.dataframe(ddf)
