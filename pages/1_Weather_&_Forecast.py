import streamlit as st
import pandas as pd
import numpy as np

from lib.data_sources import (
    geocode_place, fetch_openmeteo_archive, fetch_openmeteo_forecast,
    hourly_to_dataframe, daily_to_dataframe, summarize_daily_from_hourly,
    add_weather_desc, aggregate_daily_across_points, aggregate_hourly_across_points
)
from lib.geoutils import parse_polygon_from_output, polygon_bounds, sample_points_in_polygon

st.title("🌦️ Weather & Forecast")

with st.sidebar:
    st.header("Location")
    mode = st.radio("Select by:", ["Place name", "Latitude/Longitude", "Pick on Map", "Draw Area (Polygon)"])
    tz_str = "auto"

    if mode == "Place name":
        q = st.text_input("City/Town/Region name", value="Giresun")
        results = geocode_place(q) if q else []
        if results:
            labels = [f"{r['name']}, {r.get('admin1','')}, {r.get('country','')} ({r['latitude']:.3f}, {r['longitude']:.3f})" for r in results]
            idx = st.selectbox("Pick a location", range(len(results)), format_func=lambda i: labels[i])
            sel = results[idx]
            lat, lon = sel["latitude"], sel["longitude"]
        else:
            lat, lon = None, None

    elif mode == "Latitude/Longitude":
        lat = st.number_input("Latitude", value=st.session_state.get("picked_latlon", [0.0,0.0])[0], format="%.6f")
        lon = st.number_input("Longitude", value=st.session_state.get("picked_latlon", [0.0,0.0])[1], format="%.6f")
    else:
        lat, lon = None, None

    st.header("Historical Range")
    from datetime import date, timedelta
    today = date.today()
    default_start = today - timedelta(days=30)
    start_date = st.date_input("Start date", value=default_start, max_value=today - timedelta(days=1))
    end_date = st.date_input("End date", value=today - timedelta(days=1), min_value=start_date, max_value=today)

    st.header("Forecast")
    forecast_on = st.toggle("Show 5-Day Forecast", value=True)

    st.header("Sunny Days")
    include_mainly_clear = st.toggle("Count 'Mainly clear' as sunny", value=True)

    if mode == "Draw Area (Polygon)":
        max_points = st.slider("Sampling points inside area", 1, 25, 9, 1)
        show_points = st.checkbox("Show sampled points on map", value=True)
    else:
        max_points = 1
        show_points = False

    fetch = st.button("Fetch Data", type="primary")

if mode in ["Pick on Map", "Draw Area (Polygon)"]:
    try:
        from streamlit_folium import st_folium
        import folium
        if mode == "Pick on Map":
            st.subheader("Map Picker")
            center = st.session_state.get("picked_latlon", [40.916, 38.387])
            m = folium.Map(location=center, zoom_start=10, tiles="OpenStreetMap")
            if st.session_state.get("picked_latlon"):
                folium.Marker(st.session_state["picked_latlon"], tooltip="Selected").add_to(m)
            out = st_folium(m, height=420, use_container_width=True)
            if out and out.get("last_clicked"):
                lat_clicked = out["last_clicked"]["lat"]
                lon_clicked = out["last_clicked"]["lng"]
                st.session_state["picked_latlon"] = [lat_clicked, lon_clicked]
                st.success(f"Selected: {lat_clicked:.4f}, {lon_clicked:.4f}")
        else:
            st.subheader("Draw Orchard Area")
            from folium.plugins import Draw
            center = st.session_state.get("picked_latlon", [40.916, 38.387])
            m = folium.Map(location=center, zoom_start=12, tiles="OpenStreetMap")
            draw = Draw(export=True, position="topleft",
                        draw_options={"polyline": False, "rectangle": True, "polygon": True,
                                      "circle": False, "marker": False, "circlemarker": False},
                        edit_options={"edit": True, "remove": True})
            draw.add_to(m)
            out = st_folium(m, height=460, use_container_width=True)
            geom = parse_polygon_from_output(out)
            if geom and geom.get("type") == "Polygon":
                st.session_state["orchard_geom"] = geom
                min_lat, min_lon, max_lat, max_lon = polygon_bounds(geom)
                st.info(f"Area bounds — lat [{min_lat:.4f}, {max_lat:.4f}], lon [{min_lon:.4f}, {max_lon:.4f}]")
                pts = sample_points_in_polygon(geom, max_points=max_points)
                st.session_state["sampled_points"] = pts
                if show_points:
                    m2 = folium.Map(location=[(min_lat+max_lat)/2, (min_lon+max_lon)/2], zoom_start=12, tiles="OpenStreetMap")
                    folium.GeoJson(geom, name="Orchard").add_to(m2)
                    for (pla, plo) in pts:
                        folium.CircleMarker(location=[pla, plo], radius=4, fill=True).add_to(m2)
                    st_folium(m2, height=420, use_container_width=True, key="points_preview")
            else:
                st.info("Draw a polygon or rectangle to define your orchard.")
    except Exception as e:
        st.error("Map component not available. Install streamlit-folium and folium.")
        st.code("pip install streamlit-folium folium")

if fetch:
    from lib.data_sources import add_weather_desc  # ensure import
    if mode == "Draw Area (Polygon)":
        geom = st.session_state.get("orchard_geom")
        if not geom:
            st.warning("Please draw a polygon area first.")
            st.stop()
        sample_pts = st.session_state.get("sampled_points") or sample_points_in_polygon(geom, max_points=max_points)
        st.write(f"Sampling **{len(sample_pts)}** points inside area for aggregation.")
        daily_list, hourly_list = [], []
        with st.spinner("Downloading historical data for sampled points..."):
            for (la, lo) in sample_pts:
                hist = fetch_openmeteo_archive(la, lo, start_date.isoformat(), end_date.isoformat(), tz_str)
                h = hourly_to_dataframe(hist)
                d_api = daily_to_dataframe(hist).rename(columns={
                    "temperature_2m_min": "t_min_api",
                    "temperature_2m_max": "t_max_api",
                    "precipitation_sum": "precip_sum_api",
                    "wind_speed_10m_max": "wind_max_api",
                })
                d_from_h = summarize_daily_from_hourly(h)
                d = d_api.join(d_from_h, how="outer").sort_index()
                daily_list.append(d); hourly_list.append(h)
        ddf = aggregate_daily_across_points(daily_list)
        hdf_mean = aggregate_hourly_across_points(hourly_list)

        if "weathercode" in ddf.columns:
            sunny_codes = [0, 1] if include_mainly_clear else [0]
            ddf["sunny"] = ddf["weathercode"].isin(sunny_codes)
        ddf = add_weather_desc(ddf)

        st.subheader("Historical — Area Aggregate")
        st.dataframe(ddf)

        st.markdown("**Daily Temperature (Min / Max)**")
        if "t_min_api" in ddf.columns: st.line_chart(ddf[["t_min_api"]].dropna(), height=220)
        if "t_max_api" in ddf.columns: st.line_chart(ddf[["t_max_api"]].dropna(), height=220)
        if "rh_mean" in ddf.columns:
            st.markdown("**Daily Humidity Mean (%)**"); st.line_chart(ddf[["rh_mean"]].dropna(), height=220)
        if "dewpoint_mean" in ddf.columns:
            st.markdown("**Daily Dew Point Mean (°C)**"); st.line_chart(ddf[["dewpoint_mean"]].dropna(), height=220)
        if "precip_sum_api" in ddf.columns:
            st.markdown("**Daily Precipitation (mm)**"); st.bar_chart(ddf[["precip_sum_api"]].fillna(0), height=220)
        if "wind_max_api" in ddf.columns:
            st.markdown("**Daily Max Wind (m/s)**"); st.line_chart(ddf[["wind_max_api"]].dropna(), height=220)

        if not hdf_mean.empty:
            st.markdown("---"); st.subheader("Hourly (Area Mean) — Preview")
            st.dataframe(hdf_mean.head(120))
            if "temperature_2m" in hdf_mean.columns:
                st.markdown("**Hourly Temperature (°C)**"); st.line_chart(hdf_mean[["temperature_2m"]], height=220)
            if "relative_humidity_2m" in hdf_mean.columns:
                st.markdown("**Hourly Relative Humidity (%)**"); st.line_chart(hdf_mean[["relative_humidity_2m"]], height=220)
            if "dew_point_2m" in hdf_mean.columns:
                st.markdown("**Hourly Dew Point (°C)**"); st.line_chart(hdf_mean[["dew_point_2m"]], height=220)

    else:
        if mode == "Pick on Map":
            lat, lon = st.session_state.get("picked_latlon", [None, None])
        if lat is None or lon is None:
            st.warning("Please select or enter a valid location."); st.stop()

        c1, c2 = st.columns([1.4, 0.6], vertical_alignment="top")
        with c1:
            st.subheader("Historical")
            with st.spinner("Downloading historical data..."):
                hist = fetch_openmeteo_archive(lat, lon, start_date.isoformat(), end_date.isoformat(), tz_str)
            hdf = hourly_to_dataframe(hist)
            ddf_daily_api = daily_to_dataframe(hist)
            ddf_from_hourly = summarize_daily_from_hourly(hdf)
            if not ddf_daily_api.empty or not ddf_from_hourly.empty:
                ddf = ddf_daily_api.join(ddf_from_hourly, how="outer").sort_index().rename(columns={
                    "temperature_2m_min": "t_min_api",
                    "temperature_2m_max": "t_max_api",
                    "precipitation_sum": "precip_sum_api",
                    "wind_speed_10m_max": "wind_max_api",
                })
                ddf = add_weather_desc(ddf)
                if "weathercode" in ddf.columns:
                    sunny_codes = [0, 1] if include_mainly_clear else [0]
                    ddf["sunny"] = ddf["weathercode"].isin(sunny_codes)
                st.caption("Daily summary (API + computed means)")
                st.dataframe(ddf)

                st.markdown("**Daily Temperature (Min / Max)**")
                if "t_min_api" in ddf.columns: st.line_chart(ddf[["t_min_api"]].dropna(), height=220)
                if "t_max_api" in ddf.columns: st.line_chart(ddf[["t_max_api"]].dropna(), height=220)
                if "rh_mean" in ddf.columns: st.markdown("**Daily Humidity Mean (%)**"); st.line_chart(ddf[["rh_mean"]].dropna(), height=220)
                if "dewpoint_mean" in ddf.columns: st.markdown("**Daily Dew Point Mean (°C)**"); st.line_chart(ddf[["dewpoint_mean"]].dropna(), height=220)
                if "precip_sum_api" in ddf.columns: st.markdown("**Daily Precipitation (mm)**"); st.bar_chart(ddf[["precip_sum_api"]].fillna(0), height=220)
                if "wind_max_api" in ddf.columns: st.markdown("**Daily Max Wind (m/s)**"); st.line_chart(ddf[["wind_max_api"]].dropna(), height=220)
            else:
                st.info("No daily aggregates available.")

            if not hdf.empty:
                st.markdown("---"); st.subheader("Hourly Preview (separate charts)")
                st.caption("First 120 rows preview"); st.dataframe(hdf.head(120))
                if "temperature_2m" in hdf.columns:
                    st.markdown("**Hourly Temperature (°C)**"); st.line_chart(hdf[["temperature_2m"]], height=220)
                if "relative_humidity_2m" in hdf.columns:
                    st.markdown("**Hourly Relative Humidity (%)**"); st.line_chart(hdf[["relative_humidity_2m"]], height=220)
                if "dew_point_2m" in hdf.columns:
                    st.markdown("**Hourly Dew Point (°C)**"); st.line_chart(hdf[["dew_point_2m"]], height=220)

        with c2:
            st.subheader("Location & Quick Stats")
            st.metric("Latitude", f"{lat:.3f}"); st.metric("Longitude", f"{lon:.3f}")
            if "elevation" in hist: st.metric("Elevation", f"{hist['elevation']} m")
