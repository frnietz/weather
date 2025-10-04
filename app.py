import streamlit as st
import pandas as pd
import numpy as np
import requests
from datetime import date, timedelta, datetime
from dateutil import tz

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
        "temperature_2m_max", "temperature_2m_min", "precipitation_sum", "wind_speed_10m_max"
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
        "temperature_2m_max", "temperature_2m_min", "precipitation_sum", "wind_speed_10m_max"
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
    return df.set_index(pd.to_datetime(df["date"])).drop(columns=["date"])

def summarize_daily_from_hourly(h: pd.DataFrame) -> pd.DataFrame:
    # Build daily aggregates for core variables
    if h.empty:
        return pd.DataFrame()
    g = h.groupby(h.index.date)
    daily = pd.DataFrame({
        "t_mean": g["temperature_2m"].mean(),
        "t_min": g["temperature_2m"].min(),
        "t_max": g["temperature_2m"].max(),
        "rh_mean": g["relative_humidity_2m"].mean(),
        "dewpoint_mean": g["dew_point_2m"].mean(),
        "precip_sum": g["precipitation"].sum(),
        "wind_max": g["wind_speed_10m"].max()
    })
    daily.index = pd.to_datetime(daily.index)
    return daily

def nice_number(n):
    return None if n is None or pd.isna(n) else float(np.round(n, 2))

# --------- UI ---------
st.title("🌤️ Letta Agritech — Historical & 5‑Day Weather Dashboard")

with st.sidebar:
    st.header("Location")
    mode = st.radio("Select by:", ["Place name", "Latitude/Longitude"], horizontal=True)
    if mode == "Place name":
        q = st.text_input("City/Town/Region name", value="Giresun")
        results = geocode_place(q) if q else []
        if results:
            labels = [f"{r['name']}, {r.get('admin1','')}, {r.get('country','')} ({r['latitude']:.3f}, {r['longitude']:.3f})" for r in results]
            idx = st.selectbox("Pick a location", range(len(results)), format_func=lambda i: labels[i])
            sel = results[idx]
            lat, lon = sel["latitude"], sel["longitude"]
            tz_str = "auto"
        else:
            st.info("Type a place name to search. Example: 'Ordu' or 'Amsterdam'.")
            lat, lon, tz_str = None, None, "auto"
    else:
        lat = st.number_input("Latitude", value=40.916, format="%.6f")
        lon = st.number_input("Longitude", value=38.387, format="%.6f")
        tz_str = "auto"

    st.header("Historical Range")
    today = date.today()
    default_start = today - timedelta(days=30)
    start_date = st.date_input("Start date", value=default_start, max_value=today - timedelta(days=1))
    end_date = st.date_input("End date", value=today - timedelta(days=1), min_value=start_date, max_value=today)

    st.header("Forecast")
    forecast_on = st.toggle("Show 5‑Day Forecast", value=True)

    fetch = st.button("Fetch Data", type="primary")

# --------- Fetch & Process ---------
if fetch:
    if lat is None or lon is None:
        st.warning("Please select or enter a valid location.")
        st.stop()

    c1, c2 = st.columns([1, 1], vertical_alignment="top")
    with c1:
        st.subheader("Historical (Hourly & Daily)")
        with st.spinner("Downloading historical data..."):
            hist = fetch_openmeteo_archive(lat, lon, start_date.isoformat(), end_date.isoformat(), tz_str)

        hdf = hourly_to_dataframe(hist)
        ddf_daily_api = daily_to_dataframe(hist)
        ddf_from_hourly = summarize_daily_from_hourly(hdf)

        if hdf.empty:
            st.error("No hourly data returned for this range.")
        else:
            st.caption("Hourly data preview (first 120 rows):")
            st.dataframe(hdf.head(120))

            st.line_chart(hdf[["temperature_2m", "relative_humidity_2m", "dew_point_2m"]])

        # Merge API daily with our computed daily to include humidity/dewpoint means
        if not ddf_daily_api.empty or not ddf_from_hourly.empty:
            ddf = ddf_daily_api.join(ddf_from_hourly, how="outer").sort_index()
            ddf = ddf.rename(columns={
                "temperature_2m_min": "t_min_api",
                "temperature_2m_max": "t_max_api",
                "precipitation_sum": "precip_sum_api",
                "wind_speed_10m_max": "wind_max_api",
            })
            st.caption("Daily summary")
            st.dataframe(ddf)

            # Charts
            st.bar_chart(ddf[["t_min_api", "t_max_api"]])
            st.line_chart(ddf[["t_mean", "rh_mean", "dewpoint_mean"]].dropna(how="all"))
        else:
            st.info("No daily aggregates available.")

    with c2:
        st.subheader("Location & Quick Stats")
        st.metric("Latitude", f"{lat:.3f}")
        st.metric("Longitude", f"{lon:.3f}")
        if "elevation" in hist:
            st.metric("Elevation", f"{hist['elevation']} m")

        # Quick stats from daily
        try:
            if not ddf_from_hourly.empty:
                st.write("**Last period stats (from hourly)**")
                stats = {
                    "Avg Temp (°C)": nice_number(ddf_from_hourly["t_mean"].mean()),
                    "Min Temp (°C)": nice_number(ddf_from_hourly["t_min"].min()),
                    "Max Temp (°C)": nice_number(ddf_from_hourly["t_max"].max()),
                    "Avg RH (%)": nice_number(ddf_from_hourly["rh_mean"].mean()),
                    "Avg Dew Point (°C)": nice_number(ddf_from_hourly["dewpoint_mean"].mean()),
                    "Total Precip (mm)": nice_number(ddf_from_hourly["precip_sum"].sum()),
                    "Max Wind (m/s)": nice_number(ddf_from_hourly["wind_max"].max()),
                }
                st.table(pd.DataFrame(stats, index=["Value"]).T)
        except Exception as e:
            st.warning(f"Could not compute quick stats: {e}")

        if forecast_on:
            st.subheader("5‑Day Forecast")
            with st.spinner("Fetching forecast…"):
                fc = fetch_openmeteo_forecast(lat, lon, 5, tz_str)

            f_hourly = hourly_to_dataframe(fc)
            f_daily = daily_to_dataframe(fc)

            if not f_hourly.empty:
                st.caption("Forecast — Hourly (next 5 days)")
                st.dataframe(f_hourly.head(120))
                st.line_chart(f_hourly[["temperature_2m", "relative_humidity_2m", "dew_point_2m"]])

            if not f_daily.empty:
                st.caption("Forecast — Daily")
                st.dataframe(f_daily)
                st.bar_chart(f_daily[["temperature_2m_min", "temperature_2m_max"]])

st.markdown("---")
st.caption("Data source: Open‑Meteo (Archive & Forecast APIs). This app aggregates hourly data to daily means for humidity & dew point.")
