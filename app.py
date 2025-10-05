import streamlit as st
import pandas as pd
import numpy as np
import requests
from datetime import date, timedelta

st.set_page_config(page_title="Letta Agritech • Weather Dashboard", layout="wide")

# --------- Helpers ---------
@st.cache_data(show_spinner=False, ttl=60*30)
def geocode_place(name: str, count: int = 5):
    url = "https://geocoding-api.open-meteo.com/v1/search"
    params = {"name": name, "count": count, "language": "en", "format": "json"}
    r = requests.get(url, params=params, timeout=20)
    r.raise_for_status()
    data = r.json()
    return data.get("results", [])

@st.cache_data(show_spinner=False, ttl=60*30)
def fetch_openmeteo_archive(lat: float, lon: float, start: str, end: str, tz_str: str = "auto"):
    url = "https://archive-api.open-meteo.com/v1/archive"
    hourly_vars = [
        "temperature_2m", "relative_humidity_2m", "dew_point_2m",
        "apparent_temperature", "precipitation", "rain", "snowfall", "surface_pressure",
        "wind_speed_10m", "wind_gusts_10m", "wind_direction_10m"
    ]
    daily_vars = [
        "temperature_2m_max", "temperature_2m_min", "precipitation_sum",
        "wind_speed_10m_max", "weathercode"
    ]
    params = {
        "latitude": lat, "longitude": lon,
        "start_date": start, "end_date": end,
        "hourly": ",".join(hourly_vars),
        "daily": ",".join(daily_vars),
        "timezone": tz_str
    }
    r = requests.get(url, params=params, timeout=30)
    r.raise_for_status()
    return r.json()

@st.cache_data(show_spinner=False, ttl=60*15)
def fetch_openmeteo_forecast(lat: float, lon: float, days: int = 5, tz_str: str = "auto"):
    url = "https://api.open-meteo.com/v1/forecast"
    hourly_vars = [
        "temperature_2m", "relative_humidity_2m", "dew_point_2m",
        "apparent_temperature", "precipitation", "surface_pressure",
        "wind_speed_10m", "wind_gusts_10m", "wind_direction_10m"
    ]
    daily_vars = [
        "temperature_2m_max", "temperature_2m_min", "precipitation_sum",
        "wind_speed_10m_max", "weathercode"
    ]
    params = {
        "latitude": lat, "longitude": lon,
        "hourly": ",".join(hourly_vars),
        "daily": ",".join(daily_vars),
        "forecast_days": days,
        "timezone": tz_str
    }
    r = requests.get(url, params=params, timeout=30)
    r.raise_for_status()
    return r.json()

def hourly_to_dataframe(payload: dict) -> pd.DataFrame:
    if "hourly" not in payload: 
        return pd.DataFrame()
    hourly = payload["hourly"]
    times = pd.to_datetime(hourly.get("time", []))
    df = pd.DataFrame({"time": times})
    for k, v in hourly.items():
        if k == "time": 
            continue
        df[k] = v
    return df.set_index("time")

def daily_to_dataframe(payload: dict) -> pd.DataFrame:
    if "daily" not in payload: 
        return pd.DataFrame()
    daily = payload["daily"]
    times = pd.to_datetime(daily.get("time", []))
    df = pd.DataFrame({"date": times.date})
    for k, v in daily.items():
        if k == "time":
            continue
        df[k] = v
    df = df.set_index(pd.to_datetime(df["date"])).drop(columns=["date"])
    return df

def summarize_daily_from_hourly(h: pd.DataFrame) -> pd.DataFrame:
    if h.empty:
        return pd.DataFrame()
    g = h.groupby(h.index.date)
    daily = pd.DataFrame({
        "t_mean": g["temperature_2m"].mean(),
        "t_min_hourly": g["temperature_2m"].min(),
        "t_max_hourly": g["temperature_2m"].max(),
        "rh_mean": g["relative_humidity_2m"].mean(),
        "dewpoint_mean": g["dew_point_2m"].mean(),
        "precip_sum_hourly": g["precipitation"].sum(),
        "wind_max_hourly": g["wind_speed_10m"].max()
    })
    daily.index = pd.to_datetime(daily.index)
    return daily

def nice_number(n):
    import numpy as np, pandas as pd
    return None if n is None or pd.isna(n) else float(np.round(n, 2))

WMO_CODES = {
    0: "Clear sky",
    1: "Mainly clear",
    2: "Partly cloudy",
    3: "Overcast",
    45: "Fog",
    48: "Depositing rime fog",
    51: "Drizzle: Light",
    53: "Drizzle: Moderate",
    55: "Drizzle: Dense",
    56: "Freezing Drizzle: Light",
    57: "Freezing Drizzle: Dense",
    61: "Rain: Slight",
    63: "Rain: Moderate",
    65: "Rain: Heavy",
    66: "Freezing Rain: Light",
    67: "Freezing Rain: Heavy",
    71: "Snow fall: Slight",
    73: "Snow fall: Moderate",
    75: "Snow fall: Heavy",
    77: "Snow grains",
    80: "Rain showers: Slight",
    81: "Rain showers: Moderate",
    82: "Rain showers: Violent",
    85: "Snow showers: Slight",
    86: "Snow showers: Heavy",
    95: "Thunderstorm: Slight/Moderate",
    96: "Thunderstorm with hail: Slight",
    99: "Thunderstorm with hail: Heavy"
}

def add_weather_desc(df: pd.DataFrame) -> pd.DataFrame:
    if "weathercode" in df.columns:
        df = df.copy()
        df["weather_desc"] = df["weathercode"].map(WMO_CODES).fillna("Unknown")
    return df

# ---- Area (polygon) utilities ----
def parse_polygon_from_output(out: dict):
    # Return a GeoJSON geometry (Polygon) from st_folium output if present.
    if not out:
        return None
    g = out.get("last_active_drawing")
    if g and "geometry" in g:
        return g["geometry"]
    drawings = out.get("all_drawings")
    if drawings:
        last = drawings[-1]
        if "geometry" in last:
            return last["geometry"]
    return None

def polygon_bounds(geom: dict):
    # GeoJSON polygon: coordinates are [ [ [lon,lat], ... ] ]
    coords = geom["coordinates"][0]
    lons = [c[0] for c in coords]
    lats = [c[1] for c in coords]
    return min(lats), min(lons), max(lats), max(lons)

def sample_points_in_polygon(geom: dict, max_points: int = 9):
    # Simple grid sampler with ray casting test. Returns [(lat, lon), ...]
    def point_in_poly(lat, lon, poly):
        x = lon; y = lat
        inside = False
        n = len(poly)
        for i in range(n):
            x1, y1 = poly[i][1], poly[i][0]
            x2, y2 = poly[(i+1)%n][1], poly[(i+1)%n][0]
            cond = ((y1 > y) != (y2 > y)) and (x < (x2 - x1) * (y - y1) / (y2 - y1 + 1e-12) + x1)
            if cond:
                inside = not inside
        return inside

    coords = geom["coordinates"][0]
    poly = [(c[1], c[0]) for c in coords]  # (lat,lon)
    min_lat, min_lon, max_lat, max_lon = polygon_bounds(geom)
    import numpy as np
    n = int(np.ceil(np.sqrt(max_points)))
    lat_grid = np.linspace(min_lat, max_lat, max(2, n))
    lon_grid = np.linspace(min_lon, max_lon, max(2, n))
    pts = []
    for la in lat_grid:
        for lo in lon_grid:
            if point_in_poly(la, lo, poly):
                pts.append((la, lo))
    if not pts:
        la = float(np.mean([p[0] for p in poly]))
        lo = float(np.mean([p[1] for p in poly]))
        pts = [(la, lo)]
    if len(pts) > max_points:
        idx = np.linspace(0, len(pts)-1, max_points).astype(int).tolist()
        pts = [pts[i] for i in idx]
    return pts

def aggregate_daily_across_points(dfs):
    # Mean across points for numeric cols; weathercode as daily mode.
    if not dfs:
        return pd.DataFrame()
    aligned = [df.copy() for df in dfs]
    all_index = sorted(set().union(*[d.index for d in aligned]))
    aligned = [d.reindex(all_index) for d in aligned]
    stacked = pd.concat(aligned, axis=1, keys=range(len(aligned)))
    numeric_cols = [c for c in aligned[0].columns if c != "weathercode"]
    num = stacked.loc[:, stacked.columns.get_level_values(1).isin(numeric_cols)]
    agg_num = num.groupby(level=1, axis=1).mean(numeric_only=True)
    if "weathercode" in aligned[0].columns:
        wc = stacked.xs("weathercode", axis=1, level=1)
        wc_mode = wc.mode(axis=1)
        agg = agg_num.copy()
        if not wc_mode.empty:
            agg["weathercode"] = wc_mode.iloc[:,0]
        else:
            agg["weathercode"] = np.nan
    else:
        agg = agg_num
    return agg

def aggregate_hourly_across_points(dfs):
    # Mean across points for hourly frames (align timestamps).
    if not dfs:
        return pd.DataFrame()
    aligned = [df.copy() for df in dfs]
    all_index = sorted(set().union(*[d.index for d in aligned]))
    aligned = [d.reindex(all_index) for d in aligned]
    stacked = pd.concat(aligned, axis=1, keys=range(len(aligned)))
    agg = stacked.groupby(level=1, axis=1).mean(numeric_only=True)
    return agg

# --------- UI ---------
st.title("🌤️ Letta Agritech — Historical & 5-Day Weather Dashboard")

with st.sidebar:
    st.header("Location")
    mode = st.radio("Select by:", ["Place name", "Latitude/Longitude", "Pick on Map", "Draw Area (Polygon)"])
    tz_str = "auto"

    default_lat, default_lon = 40.916, 38.387  # Giresun-ish
    st.session_state.setdefault("picked_latlon", [default_lat, default_lon])
    st.session_state.setdefault("orchard_geom", None)

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
        lat = st.number_input("Latitude", value=st.session_state["picked_latlon"][0], format="%.6f")
        lon = st.number_input("Longitude", value=st.session_state["picked_latlon"][1], format="%.6f")

    else:
        lat, lon = None, None

    st.header("Historical Range")
    today = date.today()
    default_start = today - timedelta(days=30)
    start_date = st.date_input("Start date", value=default_start, max_value=today - timedelta(days=1))
    end_date = st.date_input("End date", value=today - timedelta(days=1), min_value=start_date, max_value=today)

    st.header("Forecast")
    forecast_on = st.toggle("Show 5-Day Forecast", value=True)

    st.header("Sunny Days")
    include_mainly_clear = st.toggle("Count 'Mainly clear' as sunny", value=True)

    if mode == "Draw Area (Polygon)":
        max_points = st.slider("Sampling points inside area", min_value=1, max_value=25, value=9, step=1)
        show_points = st.checkbox("Show sampled points on map", value=True)
    else:
        max_points = 1
        show_points = False

    fetch = st.button("Fetch Data", type="primary")

# --------- Map / Area UI ---------
if mode in ["Pick on Map", "Draw Area (Polygon)"]:
    try:
        from streamlit_folium import st_folium
        import folium
        if mode == "Pick on Map":
            st.subheader("Map Picker")
            center = st.session_state.get("picked_latlon", [default_lat, default_lon])
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
            center = st.session_state.get("picked_latlon", [default_lat, default_lon])
            m = folium.Map(location=center, zoom_start=12, tiles="OpenStreetMap")
            draw = Draw(
                export=True,
                position="topleft",
                draw_options={
                    "polyline": False, "rectangle": True, "polygon": True,
                    "circle": False, "marker": False, "circlemarker": False
                },
                edit_options={"edit": True, "remove": True}
            )
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

# --------- Fetch & Process ---------
if fetch:
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
                daily_list.append(d)
                hourly_list.append(h)

        ddf = aggregate_daily_across_points(daily_list)
        hdf_mean = aggregate_hourly_across_points(hourly_list)

        if "weathercode" in ddf.columns:
            sunny_codes = [0, 1] if include_mainly_clear else [0]
            ddf["sunny"] = ddf["weathercode"].isin(sunny_codes)
        ddf = add_weather_desc(ddf)

        st.subheader("Historical — Area Aggregate")
        st.caption("Averaged across sampled points inside the drawn polygon.")
        st.dataframe(ddf)

        st.markdown("**Daily Temperature (Min / Max)**")
        if "t_min_api" in ddf.columns:
            st.line_chart(ddf[["t_min_api"]].dropna(), height=220)
        if "t_max_api" in ddf.columns:
            st.line_chart(ddf[["t_max_api"]].dropna(), height=220)

        if "rh_mean" in ddf.columns:
            st.markdown("**Daily Humidity Mean (%)**")
            st.line_chart(ddf[["rh_mean"]].dropna(), height=220)

        if "dewpoint_mean" in ddf.columns:
            st.markdown("**Daily Dew Point Mean (°C)**")
            st.line_chart(ddf[["dewpoint_mean"]].dropna(), height=220)

        if "precip_sum_api" in ddf.columns:
            st.markdown("**Daily Precipitation (mm)**")
            st.bar_chart(ddf[["precip_sum_api"]].fillna(0), height=220)

        if "wind_max_api" in ddf.columns:
            st.markdown("**Daily Max Wind (m/s)**")
            st.line_chart(ddf[["wind_max_api"]].dropna(), height=220)

        if not hdf_mean.empty:
            st.markdown("---")
            st.subheader("Hourly (Area Mean) — Preview")
            st.dataframe(hdf_mean.head(120))
            if "temperature_2m" in hdf_mean.columns:
                st.markdown("**Hourly Temperature (°C)**")
                st.line_chart(hdf_mean[["temperature_2m"]], height=220)
            if "relative_humidity_2m" in hdf_mean.columns:
                st.markdown("**Hourly Relative Humidity (%)**")
                st.line_chart(hdf_mean[["relative_humidity_2m"]], height=220)
            if "dew_point_2m" in hdf_mean.columns:
                st.markdown("**Hourly Dew Point (°C)**")
                st.line_chart(hdf_mean[["dew_point_2m"]], height=220)

        if forecast_on:
            st.subheader("5-Day Forecast — Area Aggregate")
            f_daily_list, f_hourly_list = [], []
            with st.spinner("Fetching forecast for sampled points..."):
                for (la, lo) in sample_pts:
                    fc = fetch_openmeteo_forecast(la, lo, 5, tz_str)
                    f_hourly_list.append(hourly_to_dataframe(fc))
                    f_daily_list.append(daily_to_dataframe(fc))

            f_daily = aggregate_daily_across_points(f_daily_list)
            if "weathercode" in f_daily.columns:
                sunny_codes = [0, 1] if include_mainly_clear else [0]
                f_daily["sunny"] = f_daily["weathercode"].isin(sunny_codes)
            f_daily = add_weather_desc(f_daily)

            st.caption("Forecast — Daily (area mean)")
            st.dataframe(f_daily)

            if "temperature_2m_min" in f_daily.columns:
                st.markdown("**Forecast: Daily Min Temp (°C)**")
                st.line_chart(f_daily[["temperature_2m_min"]].dropna(), height=220)
            if "temperature_2m_max" in f_daily.columns:
                st.markdown("**Forecast: Daily Max Temp (°C)**")
                st.line_chart(f_daily[["temperature_2m_max"]].dropna(), height=220)
            if "precipitation_sum" in f_daily.columns:
                st.markdown("**Forecast: Daily Precipitation (mm)**")
                st.bar_chart(f_daily[["precipitation_sum"]].fillna(0), height=220)
            if "wind_speed_10m_max" in f_daily.columns:
                st.markdown("**Forecast: Daily Max Wind (m/s)**")
                st.line_chart(f_daily[["wind_speed_10m_max"]].dropna(), height=220)

            f_hourly_mean = aggregate_hourly_across_points(f_hourly_list)
            if not f_hourly_mean.empty:
                st.markdown("---")
                st.caption("Forecast — Hourly (area mean) preview")
                st.dataframe(f_hourly_mean.head(120))

                if "temperature_2m" in f_hourly_mean.columns:
                    st.markdown("**Hourly Temperature (°C)**")
                    st.line_chart(f_hourly_mean[["temperature_2m"]], height=220)
                if "relative_humidity_2m" in f_hourly_mean.columns:
                    st.markdown("**Hourly Relative Humidity (%)**")
                    st.line_chart(f_hourly_mean[["relative_humidity_2m"]], height=220)
                if "dew_point_2m" in f_hourly_mean.columns:
                    st.markdown("**Hourly Dew Point (°C)**")
                    st.line_chart(f_hourly_mean[["dew_point_2m"]], height=220)

    else:
        # Point-based modes
        if mode == "Pick on Map":
            lat, lon = st.session_state.get("picked_latlon", [None, None])
        if lat is None or lon is None:
            st.warning("Please select or enter a valid location.")
            st.stop()

        c1, c2 = st.columns([1.4, 0.6], vertical_alignment="top")
        with c1:
            st.subheader("Historical")
            with st.spinner("Downloading historical data..."):
                hist = fetch_openmeteo_archive(lat, lon, start_date.isoformat(), end_date.isoformat(), tz_str)

            hdf = hourly_to_dataframe(hist)
            ddf_daily_api = daily_to_dataframe(hist)
            ddf_from_hourly = summarize_daily_from_hourly(hdf)

            if not ddf_daily_api.empty or not ddf_from_hourly.empty:
                ddf = ddf_daily_api.join(ddf_from_hourly, how="outer").sort_index()
                ddf = ddf.rename(columns={
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
                if "t_min_api" in ddf.columns:
                    st.line_chart(ddf[["t_min_api"]].dropna(), height=220)
                if "t_max_api" in ddf.columns:
                    st.line_chart(ddf[["t_max_api"]].dropna(), height=220)

                st.markdown("**Daily Humidity Mean (%)**")
                if "rh_mean" in ddf.columns:
                    st.line_chart(ddf[["rh_mean"]].dropna(), height=220)

                st.markdown("**Daily Dew Point Mean (°C)**")
                if "dewpoint_mean" in ddf.columns:
                    st.line_chart(ddf[["dewpoint_mean"]].dropna(), height=220)

                st.markdown("**Daily Precipitation (mm)**")
                if "precip_sum_api" in ddf.columns:
                    st.bar_chart(ddf[["precip_sum_api"]].fillna(0), height=220)

                st.markdown("**Daily Max Wind (m/s)**")
                if "wind_max_api" in ddf.columns:
                    st.line_chart(ddf[["wind_max_api"]].dropna(), height=220)
            else:
                st.info("No daily aggregates available.")

            if not hdf.empty:
                st.markdown("---")
                st.subheader("Hourly Preview (separate charts)")
                st.caption("First 120 rows preview")
                st.dataframe(hdf.head(120))
                if "temperature_2m" in hdf.columns:
                    st.markdown("**Hourly Temperature (°C)**")
                    st.line_chart(hdf[["temperature_2m"]], height=220)
                if "relative_humidity_2m" in hdf.columns:
                    st.markdown("**Hourly Relative Humidity (%)**")
                    st.line_chart(hdf[["relative_humidity_2m"]], height=220)
                if "dew_point_2m" in hdf.columns:
                    st.markdown("**Hourly Dew Point (°C)**")
                    st.line_chart(hdf[["dew_point_2m"]], height=220)

        with c2:
            st.subheader("Location & Quick Stats")
            st.metric("Latitude", f"{lat:.3f}")
            st.metric("Longitude", f"{lon:.3f}")
            if "elevation" in hist:
                st.metric("Elevation", f"{hist['elevation']} m")

            try:
                if not ddf_from_hourly.empty:
                    st.write("**Last period stats (from hourly)**")
                    stats = {
                        "Avg Temp (°C)": nice_number(ddf_from_hourly["t_mean"].mean()),
                        "Min Temp (°C)": nice_number(ddf_from_hourly["t_min_hourly"].min()),
                        "Max Temp (°C)": nice_number(ddf_from_hourly["t_max_hourly"].max()),
                        "Avg RH (%)": nice_number(ddf_from_hourly["rh_mean"].mean()),
                        "Avg Dew Point (°C)": nice_number(ddf_from_hourly["dewpoint_mean"].mean()),
                        "Total Precip (mm)": nice_number(ddf_from_hourly["precip_sum_hourly"].sum()),
                        "Max Wind (m/s)": nice_number(ddf_from_hourly["wind_max_hourly"].max()),
                    }
                    st.table(pd.DataFrame(stats, index=["Value"]).T)
            except Exception as e:
                st.warning(f"Could not compute quick stats: {e}")

            try:
                if not ddf_daily_api.empty and "weathercode" in ddf_daily_api.columns:
                    sunny_codes = [0, 1] if include_mainly_clear else [0]
                    dtmp = ddf_daily_api.copy()
                    dtmp["sunny"] = dtmp["weathercode"].isin(sunny_codes)
                    sunny_count = int(dtmp["sunny"].sum())
                    total_days = int(dtmp.shape[0])
                    pct = 100.0 * sunny_count / total_days if total_days else 0.0
                    st.subheader("Sunny Days (Historical Range)")
                    st.metric("Sunny days", f"{sunny_count}/{total_days}")
                    st.metric("Sunny %", f"{pct:.1f}%")
            except Exception as e:
                st.warning(f"Sunny days calculation issue: {e}")

            if forecast_on:
                st.subheader("5-Day Forecast")
                with st.spinner("Fetching forecast…"):
                    fc = fetch_openmeteo_forecast(lat, lon, 5, tz_str)

                f_hourly = hourly_to_dataframe(fc)
                f_daily = daily_to_dataframe(fc)
                if "weathercode" in f_daily.columns:
                    sunny_codes = [0, 1] if include_mainly_clear else [0]
                    f_daily["sunny"] = f_daily["weathercode"].isin(sunny_codes)
                f_daily = add_weather_desc(f_daily)

                st.caption("Forecast — Daily")
                st.dataframe(f_daily)

                if "temperature_2m_min" in f_daily.columns:
                    st.markdown("**Forecast: Daily Min Temp (°C)**")
                    st.line_chart(f_daily[["temperature_2m_min"]].dropna(), height=220)
                if "temperature_2m_max" in f_daily.columns:
                    st.markdown("**Forecast: Daily Max Temp (°C)**")
                    st.line_chart(f_daily[["temperature_2m_max"]].dropna(), height=220)
                if "precipitation_sum" in f_daily.columns:
                    st.markdown("**Forecast: Daily Precipitation (mm)**")
                    st.bar_chart(f_daily[["precipitation_sum"]].fillna(0), height=220)
                if "wind_speed_10m_max" in f_daily.columns:
                    st.markdown("**Forecast: Daily Max Wind (m/s)**")
                    st.line_chart(f_daily[["wind_speed_10m_max"]].dropna(), height=220)

                if not f_hourly.empty:
                    st.markdown("---")
                    st.caption("Forecast — Hourly (preview first 120 rows)")
                    st.dataframe(f_hourly.head(120))
                    if "temperature_2m" in f_hourly.columns:
                        st.markdown("**Hourly Temperature (°C)**")
                        st.line_chart(f_hourly[["temperature_2m"]], height=220)
                    if "relative_humidity_2m" in f_hourly.columns:
                        st.markdown("**Hourly Relative Humidity (%)**")
                        st.line_chart(f_hourly[["relative_humidity_2m"]], height=220)
                    if "dew_point_2m" in f_hourly.columns:
                        st.markdown("**Hourly Dew Point (°C)**")
                        st.line_chart(f_hourly[["dew_point_2m"]], height=220)

st.markdown("---")
st.caption("Data: Open-Meteo Archive & Forecast. Area mode samples points within your polygon and averages them (min/max temps averaged across points). Sunny days = weathercode 0 (and 1 if enabled).")
