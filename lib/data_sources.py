from datetime import date, timedelta
from typing import List, Dict, Any, Optional
import requests
import pandas as pd
import numpy as np

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

def geocode_place(name: str, count: int = 5):
    url = "https://geocoding-api.open-meteo.com/v1/search"
    params = {"name": name, "count": count, "language": "en", "format": "json"}
    r = requests.get(url, params=params, timeout=20)
    r.raise_for_status()
    data = r.json()
    return data.get("results", [])

def fetch_openmeteo_archive(lat: float, lon: float, start: str, end: str, tz_str: str = "auto") -> Dict[str, Any]:
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

def fetch_openmeteo_forecast(lat: float, lon: float, days: int = 5, tz_str: str = "auto") -> Dict[str, Any]:
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

def add_weather_desc(df: pd.DataFrame) -> pd.DataFrame:
    if "weathercode" in df.columns:
        df = df.copy()
        df["weather_desc"] = df["weathercode"].map(WMO_CODES).fillna("Unknown")
    return df

def aggregate_daily_across_points(dfs: List[pd.DataFrame]) -> pd.DataFrame:
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

def aggregate_hourly_across_points(dfs: List[pd.DataFrame]) -> pd.DataFrame:
    if not dfs:
        return pd.DataFrame()
    aligned = [df.copy() for df in dfs]
    all_index = sorted(set().union(*[d.index for d in aligned]))
    aligned = [d.reindex(all_index) for d in aligned]
    stacked = pd.concat(aligned, axis=1, keys=range(len(aligned)))
    agg = stacked.groupby(level=1, axis=1).mean(numeric_only=True)
    return agg

def compute_gdd(daily_df: pd.DataFrame, base_c: float = 10.0, cap_c: Optional[float] = None) -> pd.Series:
    """Simple daily GDD from min/max temps (API min/max preferred; fallback to hourly-derived)."""
    tmin = daily_df.get("t_min_api", daily_df.get("temperature_2m_min"))
    tmax = daily_df.get("t_max_api", daily_df.get("temperature_2m_max"))
    if tmin is None or tmax is None:
        return pd.Series(dtype=float)
    tmin = tmin.copy(); tmax = tmax.copy()
    if cap_c is not None:
        tmax = tmax.clip(upper=cap_c)
    tmean = (tmin + tmax) / 2.0
    gdd = (tmean - base_c).clip(lower=0.0)
    gdd.name = "GDD"
    return gdd
