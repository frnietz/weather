import os, json
from typing import Dict, Tuple, List
import numpy as np

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")
ORCH_FILE = os.path.join(DATA_DIR, "orchards.json")

def ensure_data_dir():
    os.makedirs(DATA_DIR, exist_ok=True)

def parse_polygon_from_output(out: dict):
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
    coords = geom["coordinates"][0]
    lons = [c[0] for c in coords]; lats = [c[1] for c in coords]
    return min(lats), min(lons), max(lats), max(lons)

def sample_points_in_polygon(geom: dict, max_points: int = 9):
    def point_in_poly(lat, lon, poly):
        x = lon; y = lat; inside = False; n = len(poly)
        for i in range(n):
            x1, y1 = poly[i][1], poly[i][0]
            x2, y2 = poly[(i+1)%n][1], poly[(i+1)%n][0]
            cond = ((y1 > y) != (y2 > y)) and (x < (x2 - x1) * (y - y1) / (y2 - y1 + 1e-12) + x1)
            if cond: inside = not inside
        return inside
    coords = geom["coordinates"][0]; poly = [(c[1], c[0]) for c in coords]
    min_lat, min_lon, max_lat, max_lon = polygon_bounds(geom)
    n = int(np.ceil(np.sqrt(max_points)))
    lat_grid = np.linspace(min_lat, max_lat, max(2, n))
    lon_grid = np.linspace(min_lon, max_lon, max(2, n))
    pts = []
    for la in lat_grid:
        for lo in lon_grid:
            if point_in_poly(la, lo, poly): pts.append((la, lo))
    if not pts:
        la = float(np.mean([p[0] for p in poly])); lo = float(np.mean([p[1] for p in poly])); pts = [(la, lo)]
    if len(pts) > max_points:
        idx = np.linspace(0, len(pts)-1, max_points).astype(int).tolist(); pts = [pts[i] for i in idx]
    return pts

def load_orchards() -> Dict[str, dict]:
    ensure_data_dir()
    if not os.path.exists(ORCH_FILE): return {}
    with open(ORCH_FILE, "r", encoding="utf-8") as f:
        try: return json.load(f)
        except Exception: return {}

def save_orchards(data: Dict[str, dict]):
    ensure_data_dir()
    with open(ORCH_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def add_orchard(name: str, geom: dict):
    data = load_orchards(); data[name] = geom; save_orchards(data)

def delete_orchard(name: str):
    data = load_orchards()
    if name in data: del data[name]; save_orchards(data)

def rename_orchard(old: str, new: str):
    data = load_orchards()
    if old in data: data[new] = data.pop(old); save_orchards(data)
