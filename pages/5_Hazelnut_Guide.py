import streamlit as st
import pandas as pd
from datetime import date, timedelta
from lib.data_sources import (
    geocode_place, fetch_openmeteo_archive, hourly_to_dataframe, daily_to_dataframe,
    summarize_daily_from_hourly, add_weather_desc, monthly_from_daily, drought_proxy_flags
)
from lib.geoutils import parse_polygon_from_output, sample_points_in_polygon

st.title("🌰 Hazelnut Guide — Monthly Climate & Care")

with st.sidebar:
    st.header("Scope")
    mode = st.radio("Analyze:", ["Point (place/latlon)", "Field (polygon)"])
    tz_str = "auto"

    if mode == "Point (place/latlon)":
        pick = st.radio("Pick by:", ["Place name", "Latitude/Longitude"], horizontal=True)
        if pick == "Place name":
            q = st.text_input("City/Town/Region name", value="Giresun")
            results = geocode_place(q) if q else []
            if results:
                labels = [f"{r['name']}, {r.get('admin1','')}, {r.get('country','')} ({r['latitude']:.3f}, {r['longitude']:.3f})" for r in results]
                idx = st.selectbox("Pick a location", range(len(results)), format_func=lambda i: labels[i])
                sel = results[idx]
                lat, lon = sel["latitude"], sel["longitude"]
            else:
                lat, lon = None, None
        else:
            lat = st.number_input("Latitude", value=st.session_state.get("picked_latlon", [40.916, 38.387])[0], format="%.6f")
            lon = st.number_input("Longitude", value=st.session_state.get("picked_latlon", [40.916, 38.387])[1], format="%.6f")
    else:
        lat, lon = None, None
        st.caption("Draw a polygon on this page or use a saved field in Fields Manager.")
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
            out = st_folium(m, height=420, use_container_width=True)
            geom = out.get("last_active_drawing", {}).get("geometry") if out else None
            if not geom and out and out.get("all_drawings"):
                geom = out["all_drawings"][-1].get("geometry")
            if geom and geom.get("type") == "Polygon":
                st.session_state["orchard_geom"] = geom
                pts = sample_points_in_polygon(geom, max_points=9)
                st.session_state["sampled_points"] = pts
                st.success(f"Using {len(pts)} sampling points in polygon.")
            else:
                st.info("Draw a polygon to summarize that area.")
        except Exception as e:
            st.warning("Map component not available. Install streamlit-folium and folium.")
            st.code("pip install streamlit-folium folium")

    st.header("Reference period")
    today = date.today()
    start_date = st.date_input("Start", value=today - timedelta(days=365))
    end_date = st.date_input("End", value=today, min_value=start_date, max_value=today)
    if end_date > today:
    st.warning("End date trimmed to today (archive has no future data).")
    end_date = today
if start_date > end_date:
    st.warning("Start date was after end date — aligning to end date.")
    start_date = end_date

fetch = st.button("Build monthly guide", type="primary")

def build_guidance_table():
    rows = [
        ("Jan","Dormant","Drainage, frost protection","Structural pruning; sanitation; soil sampling","Cankers; sanitize mummies"),
        ("Feb","Dormant / catkin shed","Avoid waterlogging/frost","Finish pruning; plan nutrition","Cankers; dormant sprays if local guidance"),
        ("Mar","Budbreak","Rains okay; track frost","First N after growth; pre-emergent; sucker control","Aphids/leafrollers; bud mite"),
        ("Apr","Rapid growth","Watch dry spells","Split N if needed; maintain weed strip","Leafrollers; place traps"),
        ("May","Nut set","Irrigation may begin","Finish N by late spring; foliar only if deficient","Aphids; bud mite (region)"),
        ("Jun","Kernel growth","Irrigation important","Mow floor; maintain cover","Filbertworm monitoring; stink bugs"),
        ("Jul","Kernel fill","Irrigation critical","Avoid late heavy N; K by tests","Filbertworm timing; BMSB scouting"),
        ("Aug","Maturity approaching","Avoid water stress","Leaf sampling for nutrition; prep floor","Continue pest monitoring"),
        ("Sep","Harvest begins","Keep floor dry","Mow/sweep; timely harvest","Wasps; vertebrates"),
        ("Oct","Harvest / post","Wetter; avoid rutting","Finish harvest; remove mummies; soil tests","Sanitation for next season"),
        ("Nov","Leaf fall","High rainfall","Lime/P/K by tests; cover crop","Canker scouting after leaf drop"),
        ("Dec","Dormant","Storm season","Plan pruning; service sprayers","Rodent guards; sanitation"),
    ]
    return pd.DataFrame(rows, columns=["Month","Phenology","Climate Focus","Orchard Ops","Pest/Disease Focus"])

if fetch:
    st.subheader("1) Climate summary from your period")
    if mode == "Field (polygon)":
        geom = st.session_state.get("orchard_geom")
        pts = st.session_state.get("sampled_points", [])
        if not geom or not pts:
            st.warning("Please draw a field polygon first.")
            st.stop()
        dailies = []
        for la, lo in pts:
            try:
                hist = fetch_openmeteo_archive(la, lo, start_date.isoformat(), end_date.isoformat(), tz_str)
            except Exception as e:
                st.error(f"Archive fetch failed at point ({la:.4f}, {lo:.4f}): {e}"); st.stop()
            hdf = hourly_to_dataframe(hist)
            ddf_api = daily_to_dataframe(hist).rename(columns={
                "temperature_2m_min":"t_min_api","temperature_2m_max":"t_max_api",
                "precipitation_sum":"precip_sum_api","wind_speed_10m_max":"wind_max_api",
            })
            ddf = ddf_api.join(summarize_daily_from_hourly(hdf), how="outer").sort_index()
            ddf = add_weather_desc(ddf)
            if "weathercode" in ddf.columns:
                ddf["sunny"] = ddf["weathercode"].isin([0,1])
            dailies.append(ddf)
        if dailies:
            import numpy as np
            all_idx = sorted(set().union(*[d.index for d in dailies]))
            aligned = [d.reindex(all_idx) for d in dailies]
            stacked = pd.concat(aligned, axis=1, keys=range(len(aligned)))
            daily = stacked.groupby(level=1, axis=1).mean(numeric_only=True)
        else:
            daily = pd.DataFrame()
    else:
        if lat is None or lon is None:
            st.warning("Please select a valid point location.")
            st.stop()
        try:
        hist = fetch_openmeteo_archive(lat, lon, start_date.isoformat(), end_date.isoformat(), tz_str)
    except Exception as e:
        st.error(f"Archive fetch failed: {e}. Check that end date is not in the future and lat/lon are valid."); st.stop()
        hdf = hourly_to_dataframe(hist)
        ddf_api = daily_to_dataframe(hist).rename(columns={
            "temperature_2m_min":"t_min_api","temperature_2m_max":"t_max_api",
            "precipitation_sum":"precip_sum_api","wind_speed_10m_max":"wind_max_api",
        })
        daily = ddf_api.join(summarize_daily_from_hourly(hdf), how="outer").sort_index()
        daily = add_weather_desc(daily)
        if "weathercode" in daily.columns:
            daily["sunny"] = daily["weathercode"].isin([0,1])

    if daily.empty:
        st.warning("No daily data returned for the reference period.")
        st.stop()

    monthly = monthly_from_daily(daily)
    st.dataframe(monthly)

    if "precip_total" in monthly.columns:
        st.markdown("**Monthly precipitation (mm)**")
        st.bar_chart(monthly[["precip_total"]])
    if "tmin_mean" in monthly.columns and "tmax_mean" in monthly.columns:
        st.markdown("**Monthly temperature (mean daily min/max, °C)**")
        st.line_chart(monthly[["tmin_mean","tmax_mean"]])
    if "rh_mean" in monthly.columns:
        st.markdown("**Monthly mean RH (%)**")
        st.line_chart(monthly[["rh_mean"]])
    if "sunny_days" in monthly.columns:
        st.markdown("**Sunny days per month**")
        st.bar_chart(monthly[["sunny_days"]])
    if "heat_days_35C" in monthly.columns:
        st.markdown("**Monthly heat-stress days (≥35°C)**")
        st.bar_chart(monthly[["heat_days_35C"]])

    dr = drought_proxy_flags(monthly)
    if not dr.empty and dr.any():
        months_flagged = list(monthly.index[dr])
        st.warning(f"Drought-like months (heuristic): {', '.join(months_flagged)} — consider irrigation/soil moisture checks.")

    st.subheader("2) Best-practice tasks by month (guide)")
    guide = build_guidance_table()
    st.dataframe(guide)

    with st.expander("Actionable notes (short)"):
        for _, r in guide.iterrows():
            st.markdown(f"**{r['Month']} — {r['Phenology']}**  \n"
                        f"- Climate: {r['Climate Focus']}  \n"
                        f"- Ops: {r['Orchard Ops']}  \n"
                        f"- IPM: {r['Pest/Disease Focus']}")

    st.download_button("Download monthly climate CSV", monthly.to_csv().encode("utf-8"),
                       "monthly_climate_summary.csv", "text/csv")
    st.download_button("Download guide CSV", guide.to_csv(index=False).encode("utf-8"),
                       "hazelnut_monthly_guide.csv", "text/csv")

st.caption("Note: generalized heuristics. Calibrate with local extension guidance, cultivar, and soil/leaf analyses.")
