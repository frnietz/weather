# Letta Agritech — v6 Multi‑Page

**Pages**
1. Weather & Forecast — historical + 5‑day, min/max temp, separate charts, sunny days, polygon area aggregation.
2. Fields (Polygons) Manager — draw/save/import GeoJSON fields.
3. Satellite & Crop Analysis — satellite basemap; NDVI time series via Earth Engine.
4. Models & Alerts — GDD computation for a point or a field.

## Quickstart
```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements.txt
streamlit run app.py
```

## Notes
- Polygon data saved to `data/orchards.json`.
- For NDVI: `pip install earthengine-api geemap` and run `earthengine authenticate` once (or configure service account).
