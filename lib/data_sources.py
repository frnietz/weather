from typing import List, Dict, Any, Optional
import requests
import pandas as pd
import numpy as np

WMO_CODES = {
    0: "Clear sky", 1: "Mainly clear", 2: "Partly cloudy", 3: "Overcast",
    45: "Fog", 48: "Depositing rime fog",
    51: "Drizzle: Light", 53: "Drizzle: Moderate", 55: "Drizzle: Dense",
    56: "Freezing Drizzle: Light", 57: "Freezing Drizzle: Dense",
    61: "Rain: Slight", 63: "Rain: Moderate", 65: "Rain: Heavy",
    66: "Freezing Rain: Light", 67: "Freezing Rain: Heavy",
    71: "Snow fall: Slight", 73: "Snow fall: Moderate", 75: "Snow fall: Heavy",
    77: "Snow grains", 80: "Rain showers: Slight", 81: "Rain showers: Moderate", 82: "Rain showers: Violent",
    85: "Snow showers: Slight", 86: "Snow showers: Heavy",
    95: "Thunderstorm: Slight/Moderate", 96: "Thunderstorm with hail: Slight", 99: "Thunderstorm with hail: Heavy"
}

def geocode_place(name: str, count: int = 5):
    url = "https://geocoding-api.open-meteo.com/v1/search"
    params = {"name": name, "count": count, "language": "en", "format": "json"}
    r = requests.get(url, params=params, timeout=20); r.raise_for_status()
    return r.json().get("results", [])

def fetch_openmeteo_archive(lat: float, lon: float, start: str, end: str, tz_str: str = "auto") -> Dict[str, Any]:
    url = "https://archive-api.open-meteo.com/v1/archive"
    hourly_vars = [
        "temperature_2m","relative_humidity_2m","dew_point_2m","apparent_temperature",
        "precipitation","rain","snowfall","surface_pressure","wind_speed_10m","wind_gusts_10m","wind_direction_10m"
    ]
    daily_vars = ["temperature_2m_max","temperature_2m_min","precipitation_sum","wind_speed_10m_max","weathercode"]
    params = {
        "latitude": lat, "longitude": lon,
        "start_date": start, "end_date": end,
        "hourly": ",".join(hourly_vars), "daily": ",".join(daily_vars),
        "timezone": tz_str
    }
    r = requests.get(url, params=params, timeout=30); r.raise_for_status()
    return r.json()

def fetch_openmeteo_forecast(lat: float, lon: float, days: int = 5, tz_str: str = "auto") -> Dict[str, Any]:
    url = "https://api.open-meteo.com/v1/forecast"
    hourly_vars = [
        "temperature_2m","relative_humidity_2m","dew_point_2m","apparent_temperature",
        "precipitation","surface_pressure","wind_speed_10m","wind_gusts_10m","wind_direction_10m"
    ]
    daily_vars = ["temperature_2m_max","temperature_2m_min","precipitation_sum","wind_speed_10m_max","weathercode"]
    params = {"latitude": lat,"longitude": lon,"hourly": ",".join(hourly_vars),
              "daily": ",".join(daily_vars),"forecast_days": days,"timezone": tz_str}
    r = requests.get(url, params=params, timeout=30); r.raise_for_status()
    return r.json()

def hourly_to_dataframe(payload: dict) -> pd.DataFrame:
    if "hourly" not in payload: return pd.DataFrame()
    h = payload["hourly"]; times = pd.to_datetime(h.get("time", []))
    df = pd.DataFrame({"time": times})
    for k, v in h.items():
        if k != "time": df[k] = v
    return df.set_index("time")

def daily_to_dataframe(payload: dict) -> pd.DataFrame:
    if "daily" not in payload: return pd.DataFrame()
    d = payload["daily"]; times = pd.to_datetime(d.get("time", []))
    df = pd.DataFrame({"date": times.date})
    for k, v in d.items():
        if k != "time": df[k] = v
    df = df.set_index(pd.to_datetime(df["date"])).drop(columns=["date"])
    return df

def summarize_daily_from_hourly(h: pd.DataFrame) -> pd.DataFrame:
    if h.empty: return pd.DataFrame()
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
        df = df.copy(); df["weather_desc"] = df["weathercode"].map(WMO_CODES).fillna("Unknown")
    return df

def aggregate_daily_across_points(dfs: List[pd.DataFrame]) -> pd.DataFrame:
    if not dfs: return pd.DataFrame()
    aligned = [d.copy() for d in dfs]
    idx = sorted(set().union(*[d.index for d in aligned]))
    aligned = [d.reindex(idx) for d in aligned]
    stacked = pd.concat(aligned, axis=1, keys=range(len(aligned)))
    numeric_cols = [c for c in aligned[0].columns if c != "weathercode"]
    num = stacked.loc[:, stacked.columns.get_level_values(1).isin(numeric_cols)]
    agg_num = num.groupby(level=1, axis=1).mean(numeric_only=True)
    if "weathercode" in aligned[0].columns:
        wc = stacked.xs("weathercode", axis=1, level=1); wc_mode = wc.mode(axis=1)
        agg = agg_num.copy(); agg["weathercode"] = wc_mode.iloc[:,0] if not wc_mode.empty else np.nan
    else:
        agg = agg_num
    return agg

def aggregate_hourly_across_points(dfs: List[pd.DataFrame]) -> pd.DataFrame:
    if not dfs: return pd.DataFrame()
    aligned = [d.copy() for d in dfs]
    idx = sorted(set().union(*[d.index for d in aligned]))
    aligned = [d.reindex(idx) for d in aligned]
    stacked = pd.concat(aligned, axis=1, keys=range(len(aligned)))
    return stacked.groupby(level=1, axis=1).mean(numeric_only=True)

def compute_gdd(daily_df: pd.DataFrame, base_c: float = 10.0, cap_c: Optional[float] = None) -> pd.Series:
    tmin = daily_df.get("t_min_api", daily_df.get("temperature_2m_min"))
    tmax = daily_df.get("t_max_api", daily_df.get("temperature_2m_max"))
    if tmin is None or tmax is None: return pd.Series(dtype=float)
    tmin = tmin.copy(); tmax = tmax.copy()
    if cap_c is not None: tmax = tmax.clip(upper=cap_c)
    tmean = (tmin + tmax) / 2.0
    gdd = (tmean - base_c).clip(lower=0.0); gdd.name = "GDD"
    return gdd

# ---------- Monthly & Weekly aggregation helpers ----------
def monthly_from_daily(daily_df: pd.DataFrame) -> pd.DataFrame:
    if daily_df is None or daily_df.empty: return pd.DataFrame()
    df = daily_df.copy(); df.index = pd.to_datetime(df.index)
    df["month"] = df.index.to_period("M").astype(str)

    tmin = df.get("t_min_api", df.get("temperature_2m_min"))
    tmax = df.get("t_max_api", df.get("temperature_2m_max"))
    rh   = df.get("rh_mean")
    dpt  = df.get("dewpoint_mean")
    pr   = df.get("precip_sum_api", df.get("precipitation_sum", pd.Series(index=df.index, dtype=float)))
    wc   = df.get("weathercode")
    sunny = df.get("sunny") if "sunny" in df.columns else (wc.isin([0,1]) if wc is not None else None)

    agg = pd.DataFrame(index=sorted(df["month"].unique()))
    if tmin is not None: agg["tmin_mean"] = df.groupby("month")[tmin.name].mean()
    if tmax is not None: agg["tmax_mean"] = df.groupby("month")[tmax.name].mean()
    if rh is not None:   agg["rh_mean"]   = df.groupby("month")[rh.name].mean()
    if dpt is not None:  agg["dew_mean"]  = df.groupby("month")[dpt.name].mean()
    if pr is not None:
        agg["precip_total"] = df.groupby("month")[pr.name].sum()
        agg["rainy_days"]   = df.groupby("month")[(pr > 1.0)].sum()
        agg["dry_days"]     = df.groupby("month")[(pr < 1.0)].sum()
    if sunny is not None: agg["sunny_days"] = df.groupby("month")[sunny.name].sum()
    if tmax is not None:
        agg["heat_days_32C"] = df.groupby("month")[(tmax >= 32.0)].sum()
        agg["heat_days_35C"] = df.groupby("month")[(tmax >= 35.0)].sum()
    if tmin is not None:
        agg["frost_days_0C"]  = df.groupby("month")[(tmin <= 0.0)].sum()
        agg["frost_days_-2C"] = df.groupby("month")[(tmin <= -2.0)].sum()
    return agg

def weekly_precip_from_daily(daily_df: pd.DataFrame, week_label: str = "W-MON") -> pd.DataFrame:
    """Return weekly precipitation sums using pandas resample on the daily precip column(s)."""
    if daily_df is None or daily_df.empty: return pd.DataFrame()
    df = daily_df.copy(); df.index = pd.to_datetime(df.index)
    pr = df.get("precip_sum_api", df.get("precipitation_sum"))
    if pr is None: return pd.DataFrame()
    wk = pr.resample(week_label).sum().to_frame("precip_week_sum")
    wk["week_start"] = wk.index.to_period("W-MON").start_time.date
    wk["week_end"] = wk.index.to_period("W-MON").end_time.date
    wk["month"] = wk.index.to_period("M").astype(str)
    return wk

def count_heat_days_in_month(daily_df: pd.DataFrame, month:int, threshold_c: float = 35.0) -> int:
    if daily_df is None or daily_df.empty: return 0
    df = daily_df.copy(); df.index = pd.to_datetime(df.index)
    tmax = df.get("t_max_api", df.get("temperature_2m_max"))
    if tmax is None: return 0
    sel = df[df.index.month == month]
    return int((sel[tmax.name] >= threshold_c).sum())

def drought_proxy_flags(monthly_df: pd.DataFrame) -> pd.Series:
    if monthly_df is None or monthly_df.empty: return pd.Series(dtype=bool)
    pt = monthly_df.get("precip_total", pd.Series([0]*len(monthly_df), index=monthly_df.index))
    dd = monthly_df.get("dry_days", pd.Series([0]*len(monthly_df), index=monthly_df.index))
    return (pt < 30.0) & (dd > 20)
