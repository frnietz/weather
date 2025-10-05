import streamlit as st
import pandas as pd
from datetime import date, timedelta
from lib.data_sources import (
    geocode_place, fetch_openmeteo_archive, daily_to_dataframe,
    add_weather_desc, summarize_daily_from_hourly, hourly_to_dataframe, compute_gdd
)
from lib.geoutils import load_orchards, sample_points_in_polygon

st.title("📈 Models & Alerts — Growing Degree Days (GDD)")

mode = st.radio("Compute for:", ["Point (lat/lon)", "Field (polygon)"], horizontal=True)

if mode == "Point (lat/lon)":
    lat = st.number_input("Latitude", value=st.session_state.get("picked_latlon", [40.916, 38.387])[0], format="%.6f")
    lon = st.number_input("Longitude", value=st.session_state.get("picked_latlon", [40.916, 38.387])[1], format="%.6f")
else:
    orch = load_orchards()
    if not orch:
        st.warning("No fields saved. Use Fields Manager first.")
    else:
        name = st.selectbox("Field", list(orch.keys()))
        geom = orch[name]
        pts = sample_points_in_polygon(geom, max_points=9)
        st.caption(f"Sampling {len(pts)} points inside field for area mean.")

today = date.today()
start = st.date_input("Start date", value=date(today.year, 4, 1))
end = st.date_input("End date", value=min(date(today.year, 10, 31), today))
base_c = st.number_input("Base temperature (°C)", value=10.0, step=0.5)
cap_c = st.number_input("Upper cap (°C, optional)", value=35.0, step=0.5)

if st.button("Compute GDD", type="primary"):
    tz_str = "auto"
    if mode == "Point (lat/lon)":
        hist = fetch_openmeteo_archive(lat, lon, start.isoformat(), end.isoformat(), tz_str)
        ddf_api = daily_to_dataframe(hist).rename(columns={
            "temperature_2m_min": "t_min_api",
            "temperature_2m_max": "t_max_api",
        })
        hdf = hourly_to_dataframe(hist)
        ddf_from_h = summarize_daily_from_hourly(hdf)
        ddf = ddf_api.join(ddf_from_h, how="outer").sort_index()
    else:
        daily_list = []
        for (la, lo) in pts:
            hist = fetch_openmeteo_archive(la, lo, start.isoformat(), end.isoformat(), tz_str)
            ddf_api = daily_to_dataframe(hist).rename(columns={
                "temperature_2m_min": "t_min_api",
                "temperature_2m_max": "t_max_api",
            })
            hdf = hourly_to_dataframe(hist)
            ddf_from_h = summarize_daily_from_hourly(hdf)
            ddf = ddf_api.join(ddf_from_h, how="outer").sort_index()
            daily_list.append(ddf)
        # simple mean across points
        if daily_list:
            import numpy as np
            aligned = [d.copy() for d in daily_list]
            all_idx = sorted(set().union(*[d.index for d in aligned]))
            aligned = [d.reindex(all_idx) for d in aligned]
            stacked = pd.concat(aligned, axis=1, keys=range(len(aligned)))
            numeric_cols = stacked.columns.get_level_values(1).unique().tolist()
            ddf = stacked.groupby(level=1, axis=1).mean(numeric_only=True)
        else:
            ddf = pd.DataFrame()

    if ddf.empty:
        st.warning("No data returned.")
    else:
        gdd = compute_gdd(ddf, base_c=base_c, cap_c=cap_c)
        if gdd.empty:
            st.warning("Could not compute GDD (missing min/max).")
        else:
            st.subheader("Daily GDD")
            st.line_chart(gdd.to_frame())
            st.metric("Season GDD total", f"{gdd.sum():.0f}")
            st.dataframe(ddf.join(gdd, how="left"))
