import streamlit as st
import pandas as pd
from datetime import date, timedelta
from lib.data_sources import (
    geocode_place, fetch_openmeteo_archive, fetch_openmeteo_forecast,
    hourly_to_dataframe, daily_to_dataframe, summarize_daily_from_hourly,
    monthly_from_daily, weekly_precip_from_daily, count_heat_days_in_month, compute_gdd, add_weather_desc
)
from lib.geoutils import parse_polygon_from_output, sample_points_in_polygon

st.title("🚨 Models & Alerts — GDD + Guide-linked Alerts")

tabs = st.tabs(["Growing Degree Days (GDD)", "Guide-linked Alerts"])

# ---------------- GDD TAB ----------------
with tabs[0]:
    mode = st.radio("Compute for:", ["Point (lat/lon)", "Field (polygon)"], horizontal=True, key="gdd_mode")
    if mode == "Point (lat/lon)":
        lat = st.number_input("Latitude", value=st.session_state.get("picked_latlon", [40.916, 38.387])[0], format="%.6f", key="gdd_lat")
        lon = st.number_input("Longitude", value=st.session_state.get("picked_latlon", [40.916, 38.387])[1], format="%.6f", key="gdd_lon")
    else:
        st.caption("Draw a polygon below or switch to Fields page to save one.")
        try:
            from streamlit_folium import st_folium
            import folium
            from folium.plugins import Draw
            center = st.session_state.get("picked_latlon", [40.916, 38.387])
            m = folium.Map(location=center, zoom_start=12, tiles="OpenStreetMap")
            Draw(export=True).add_to(m)
            out = st_folium(m, height=300, use_container_width=True, key="gdd_draw")
            geom = parse_polygon_from_output(out)
            if geom and geom.get("type") == "Polygon":
                pts = sample_points_in_polygon(geom, max_points=9)
                st.success(f"Using {len(pts)} sampling points in polygon.")
            else:
                pts = None
        except Exception as e:
            st.error("Map component missing: install streamlit-folium & folium"); pts = None

    today = date.today()
    start = st.date_input("Start date", value=date(today.year, 4, 1), key="gdd_start")
    end = st.date_input("End date", value=min(date(today.year, 10, 31), today), key="gdd_end")
    base_c = st.number_input("Base temperature (°C)", value=10.0, step=0.5, key="gdd_base")
    cap_c = st.number_input("Upper cap (°C, optional)", value=35.0, step=0.5, key="gdd_cap")

    if st.button("Compute GDD", type="primary", key="gdd_btn"):
        tz_str = "auto"
        if mode == "Point (lat/lon)":
            hist = fetch_openmeteo_archive(lat, lon, start.isoformat(), end.isoformat(), tz_str)
            ddf_api = daily_to_dataframe(hist).rename(columns={
                "temperature_2m_min":"t_min_api","temperature_2m_max":"t_max_api"})
            hdf = hourly_to_dataframe(hist)
            ddf_from_h = summarize_daily_from_hourly(hdf)
            ddf = ddf_api.join(ddf_from_h, how="outer").sort_index()
        else:
            if not pts:
                st.warning("Please draw a polygon field."); st.stop()
            dailies = []
            for (la, lo) in pts:
                hist = fetch_openmeteo_archive(la, lo, start.isoformat(), end.isoformat(), tz_str)
                ddf_api = daily_to_dataframe(hist).rename(columns={
                    "temperature_2m_min":"t_min_api","temperature_2m_max":"t_max_api"})
                hdf = hourly_to_dataframe(hist)
                ddf_from_h = summarize_daily_from_hourly(hdf)
                ddf = ddf_api.join(ddf_from_h, how="outer").sort_index(); dailies.append(ddf)
            import numpy as np
            all_idx = sorted(set().union(*[d.index for d in dailies])); aligned = [d.reindex(all_idx) for d in dailies]
            stacked = pd.concat(aligned, axis=1, keys=range(len(aligned))); ddf = stacked.groupby(level=1, axis=1).mean(numeric_only=True)

        if ddf.empty: st.warning("No data returned.")
        else:
            gdd = compute_gdd(ddf, base_c=base_c, cap_c=cap_c)
            st.subheader("Daily GDD"); st.line_chart(gdd.to_frame())
            st.metric("Season GDD total", f"{gdd.sum():.0f}")
            st.dataframe(ddf.join(gdd, how="left"))

# ---------------- ALERTS TAB ----------------
with tabs[1]:
    st.markdown("Configure alerts that mirror the **Hazelnut Guide**: drought-like weeks in **Jun–Aug** and **heat-day** accumulation in **July** (customizable).")

    mode_a = st.radio("Evaluate alerts for:", ["Point (lat/lon)", "Field (polygon)"], horizontal=True, key="al_mode")
    if mode_a == "Point (lat/lon)":
        lat_a = st.number_input("Latitude", value=st.session_state.get("picked_latlon", [40.916, 38.387])[0], format="%.6f", key="al_lat")
        lon_a = st.number_input("Longitude", value=st.session_state.get("picked_latlon", [40.916, 38.387])[1], format="%.6f", key="al_lon")
        pts_a = None
    else:
        try:
            from streamlit_folium import st_folium
            import folium
            from folium.plugins import Draw
            center = st.session_state.get("picked_latlon", [40.916, 38.387])
            m = folium.Map(location=center, zoom_start=12, tiles="OpenStreetMap")
            Draw(export=True).add_to(m)
            out = st_folium(m, height=300, use_container_width=True, key="al_draw")
            geom = parse_polygon_from_output(out)
            if geom and geom.get("type") == "Polygon":
                pts_a = sample_points_in_polygon(geom, max_points=9); st.success(f"Using {len(pts_a)} sampling points.")
            else:
                pts_a = None; st.info("Draw a polygon or switch to point mode.")
        except Exception as e:
            st.error("Map component missing: install streamlit-folium & folium"); pts_a=None

    st.subheader("Alert rules")
    c1, c2 = st.columns(2)
    with c1:
        st.markdown("**Drought-like (weekly precip)**")
        weeks_months = st.multiselect("Months to monitor", options=list(range(1,13)), default=[6,7,8], format_func=lambda m: ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"][m-1])
        weekly_precip_threshold = st.number_input("Weekly precip threshold (mm)", value=25.0, step=1.0)
    with c2:
        st.markdown("**Heat-day accumulation**")
        heat_month = st.selectbox("Month", options=list(range(1,13)), index=6, format_func=lambda m: ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"][m-1])
        heat_temp_thresh = st.number_input("Heat day Tmax threshold (°C)", value=35.0, step=0.5)
        heat_count_thresh = st.number_input("Trigger if days ≥", value=3, step=1)

    ref_days = st.slider("Reference period (days back from today)", min_value=60, max_value=730, value=365, step=15)
    run_alerts = st.button("Evaluate alerts", type="primary")

    if run_alerts:
        tz_str = "auto"
        today = date.today()
        start_hist = (today - timedelta(days=int(ref_days))).isoformat()
        end_hist = today.isoformat()

        def build_daily_for_point(la, lo):
            hist = fetch_openmeteo_archive(la, lo, start_hist, end_hist, tz_str)
            hdf = hourly_to_dataframe(hist)
            ddf_api = daily_to_dataframe(hist).rename(columns={
                "temperature_2m_min":"t_min_api","temperature_2m_max":"t_max_api",
                "precipitation_sum":"precip_sum_api","wind_speed_10m_max":"wind_max_api",
            })
            ddf = ddf_api.join(summarize_daily_from_hourly(hdf), how="outer").sort_index()
            return add_weather_desc(ddf)

        if mode_a == "Point (lat/lon)":
            daily = build_daily_for_point(lat_a, lon_a)
        else:
            if not pts_a:
                st.warning("Please draw a polygon."); st.stop()
            dailies = [build_daily_for_point(la, lo) for (la, lo) in pts_a]
            import numpy as np
            all_idx = sorted(set().union(*[d.index for d in dailies])); aligned = [d.reindex(all_idx) for d in dailies]
            stacked = pd.concat(aligned, axis=1, keys=range(len(aligned)))
            daily = stacked.groupby(level=1, axis=1).mean(numeric_only=True)

        if daily.empty:
            st.warning("No data returned for alerts."); st.stop()

        # --- Drought-like weeks ---
        weekly = weekly_precip_from_daily(daily)
        if weekly.empty:
            st.info("No precipitation data to compute weekly sums.")
        else:
            weekly["month_num"] = pd.to_datetime(weekly.index).month
            sel = weekly[weekly["month_num"].isin(weeks_months)]
            drought_weeks = sel[sel["precip_week_sum"] < weekly_precip_threshold]
            st.subheader("Weekly precipitation (selected months)")
            st.dataframe(sel[["precip_week_sum","week_start","week_end"]])

            st.markdown("**Weeks below threshold**")
            if drought_weeks.empty:
                st.success("No drought-like weeks detected under current threshold.")
            else:
                st.error(f"{len(drought_weeks)} week(s) flagged:")
                st.dataframe(drought_weeks[["precip_week_sum","week_start","week_end"]])

        # --- Heat-day accumulation ---
        count = count_heat_days_in_month(daily, month=heat_month, threshold_c=float(heat_temp_thresh))
        st.subheader("Heat day accumulation")
        st.write(f"In **{['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'][heat_month-1]}**, days with Tmax ≥ {heat_temp_thresh:.1f}°C: **{count}**")
        if count >= int(heat_count_thresh):
            st.error("Heat-day alert TRIGGERED (meets/exceeds threshold).")
        else:
            st.success("Heat-day alert NOT triggered under current threshold.")

        # --- Simple forecast peek (next 5 days) ---
        st.markdown("---")
        st.subheader("Forecast peek (next 5 days)")
        if mode_a == "Point (lat/lon)":
            la, lo = lat_a, lon_a
        else:
            la, lo = pts_a[0]  # use first point as proxy for area forecast
        fc = fetch_openmeteo_forecast(la, lo, days=5, tz_str=tz_str)
        ddf_fc = daily_to_dataframe(fc).rename(columns={"precipitation_sum":"precip_sum_api","temperature_2m_max":"t_max_api"})
        if ddf_fc.empty:
            st.info("No forecast daily data available.")
        else:
            st.dataframe(ddf_fc)
            next7_precip = ddf_fc["precip_sum_api"].sum() if "precip_sum_api" in ddf_fc.columns else float("nan")
            st.write(f"**5‑day precip total:** {next7_precip:.1f} mm")
            if next7_precip < weekly_precip_threshold:
                st.warning("Forecasted 5‑day precipitation is below your weekly threshold — watch irrigation.")
            hot_days_fc = int((ddf_fc.get("t_max_api", pd.Series()) >= float(heat_temp_thresh)).sum())
            st.write(f"**5‑day heat days (≥{heat_temp_thresh:.1f}°C):** {hot_days_fc}")
            if hot_days_fc >= int(heat_count_thresh):
                st.warning("Forecast indicates heat-day accumulation at/above your threshold.")
