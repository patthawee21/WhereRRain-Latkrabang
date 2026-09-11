"""
analyzer.py — หัวใจของระบบ: ดาวน์โหลดภาพเรดาร์ + วิเคราะห์ + ติดตามการเคลื่อนที่
"""
import io
import json
import os
from datetime import datetime, timezone

import numpy as np
import requests
from PIL import Image
from skimage import measure

import config
from geo import Georeferencer, color_to_dbz


def _in_excluded_box(x, y):
    for (x1, y1, x2, y2) in getattr(config, "EXCLUDE_BOXES", []):
        if x1 <= x <= x2 and y1 <= y <= y2:
            return True
    return False


os.makedirs(config.DATA_DIR, exist_ok=True)
STATE_FILE = os.path.join(config.DATA_DIR, "last_state.json")

georef = Georeferencer()

GRID_STEP = 2  # เว้นทุก 2px เพื่อความเร็ว (ปรับได้ตามสเปกเครื่อง — ยิ่งเล็กยิ่งละเอียดแต่ช้าลง)


def download_radar_image():
    resp = requests.get(config.RADAR_IMAGE_URL, timeout=15, headers={
        "User-Agent": "Mozilla/5.0 (rain-alert-app/1.0)"
    })
    resp.raise_for_status()
    return Image.open(io.BytesIO(resp.content)).convert("RGB")


def km_per_pixel():
    """ประมาณ km/พิกเซล คร่าวๆ จากการแปลงจุดสองจุดใกล้กัน รอบตำแหน่งผู้ใช้"""
    user_px, user_py = georef.latlon_to_pixel(config.USER_LAT, config.USER_LON)
    lat2, lon2 = georef.pixel_to_latlon(user_px + 10, user_py)
    km_per_10px = georef.km_between((config.USER_LAT, config.USER_LON), (lat2, lon2))
    return max(km_per_10px / 10.0, 1e-6)


def build_dbz_grid(image):
    """
    สแกนพื้นที่รอบตำแหน่งผู้ใช้ (ในรัศมี SCAN_RADIUS_KM) แล้วสร้าง "กริด 2 มิติ" ของค่า dBZ
    กริดนี้คือข้อมูลตั้งต้นสำหรับทั้งการหาจุดฝนที่ใกล้ที่สุด และการวาดรูปทรงจริงของกลุ่มฝน
    (จุดที่ไม่มีสีฝนจะถูกเก็บเป็น 0.0 ทำหน้าที่เป็น "พื้นน้ำทะเล" ให้ contour ตัดขอบเขตฝนได้ถูกต้อง)

    คืนค่า: (Z, x_min, y_min, step, km_per_px)
      Z คือ numpy array 2D ขนาด (n_rows, n_cols) โดย Z[row, col] = dBZ ที่พิกเซล
      (x_min + col*step, y_min + row*step)
    """
    w, h = image.size
    px = image.load()
    step = GRID_STEP
    kpp = km_per_pixel()
    scan_radius_px = int(config.SCAN_RADIUS_KM / kpp)

    user_px, user_py = georef.latlon_to_pixel(config.USER_LAT, config.USER_LON)
    x_min = max(0, int(user_px - scan_radius_px))
    x_max = min(w, int(user_px + scan_radius_px))
    y_min = max(0, int(user_py - scan_radius_px))
    y_max = min(h, int(user_py + scan_radius_px))

    xs = list(range(x_min, x_max, step))
    ys = list(range(y_min, y_max, step))
    Z = np.zeros((len(ys), len(xs)), dtype=np.float32)

    for row, y in enumerate(ys):
        for col, x in enumerate(xs):
            if _in_excluded_box(x, y):
                continue
            dbz = color_to_dbz(px[x, y])
            if dbz is not None:
                Z[row, col] = dbz

    return Z, x_min, y_min, step, kpp


def grid_to_points(Z, x_min, y_min, step):
    """แปลงกริดเป็นรายการจุดฝน (เฉพาะที่ >= threshold) พร้อม lat/lon/ระยะห่างจากผู้ใช้"""
    rows, cols = np.where(Z >= config.RAIN_DBZ_THRESHOLD)
    points = []
    for r, c in zip(rows, cols):
        x = x_min + c * step
        y = y_min + r * step
        lat, lon = georef.pixel_to_latlon(x, y)
        dist_km = georef.km_between((config.USER_LAT, config.USER_LON), (lat, lon))
        if dist_km <= config.SCAN_RADIUS_KM:
            points.append({"lat": lat, "lon": lon, "dbz": float(Z[r, c]), "dist_km": dist_km})
    return points


def extract_shape_geojson(Z, x_min, y_min, step, km_per_px):
    """
    ใช้ marching-squares (skimage.measure.find_contours) หาเส้นขอบเขตของกลุ่มฝน
    ที่แต่ละระดับความแรง (CONTOUR_LEVELS) แล้วแปลงเป็น GeoJSON polygon จริง
    ตามพิกัด lat/lon และขนาดจริงบนพื้นโลก (ไม่ใช่แค่จุด centroid อีกต่อไป)
    """
    features = []
    cell_area_km2 = (step * km_per_px) ** 2

    for level, color, opacity in config.CONTOUR_LEVELS:
        if Z.max() < level:
            continue
        try:
            contours = measure.find_contours(Z, level)
        except Exception:
            continue

        for contour in contours:
            if len(contour) < 4:
                continue
            coords = []
            for r, c in contour:
                x = x_min + c * step
                y = y_min + r * step
                lat, lon = georef.pixel_to_latlon(x, y)
                coords.append([lon, lat])  # GeoJSON ใช้ลำดับ [lon, lat]
            if coords[0] != coords[-1]:
                coords.append(coords[0])  # ปิดรูปหลายเหลี่ยมให้ครบวง

            # พื้นที่โดยประมาณของรูปทรงนี้ (จำนวนพิกเซลภายในระดับนี้ x พื้นที่ต่อพิกเซล)
            area_km2 = round(float(np.sum(Z >= level)) * cell_area_km2, 1)

            features.append({
                "type": "Feature",
                "properties": {"level_dbz": level, "color": color, "opacity": opacity, "area_km2": area_km2},
                "geometry": {"type": "Polygon", "coordinates": [coords]},
            })

    return {"type": "FeatureCollection", "features": features}


def summarize(rain_points, Z=None, km_per_px=None):
    if not rain_points:
        return None
    nearest = min(rain_points, key=lambda p: p["dist_km"])
    max_dbz = max(p["dbz"] for p in rain_points)
    strong = [p for p in rain_points if p["dbz"] >= max_dbz - 5] or rain_points
    centroid_lat = float(np.mean([p["lat"] for p in strong]))
    centroid_lon = float(np.mean([p["lon"] for p in strong]))

    total_area_km2 = None
    if Z is not None and km_per_px is not None:
        cell_area_km2 = (GRID_STEP * km_per_px) ** 2
        total_area_km2 = round(float(np.sum(Z >= config.RAIN_DBZ_THRESHOLD)) * cell_area_km2, 1)

    return {
        "nearest_km": round(nearest["dist_km"], 1),
        "nearest_dbz": nearest["dbz"],
        "max_dbz": max_dbz,
        "centroid_lat": centroid_lat,
        "centroid_lon": centroid_lon,
        "cell_count": len(rain_points),
        "total_area_km2": total_area_km2,
    }


def load_last_state():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return None


def save_state(state):
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def estimate_motion(prev_state, cur_summary, dt_seconds):
    """
    เทียบตำแหน่ง centroid ของกลุ่มฝนระหว่างสองเฟรม เพื่อประมาณทิศทาง+ความเร็ว (km/h)
    แบบง่าย (centroid tracking) — ใช้ได้ดีเมื่อมีกลุ่มฝนก้อนหลักชัดเจนไม่กี่ก้อน
    """
    if not prev_state or not prev_state.get("summary") or dt_seconds <= 0:
        return None
    prev = prev_state["summary"]
    dist_km = georef.km_between(
        (prev["centroid_lat"], prev["centroid_lon"]),
        (cur_summary["centroid_lat"], cur_summary["centroid_lon"]),
    )
    speed_kmh = dist_km / (dt_seconds / 3600.0)

    approaching = cur_summary["nearest_km"] < prev["nearest_km"]
    closing_speed_kmh = (prev["nearest_km"] - cur_summary["nearest_km"]) / (dt_seconds / 3600.0)

    eta_minutes = None
    if approaching and closing_speed_kmh > 0.5:
        eta_minutes = round((cur_summary["nearest_km"] / closing_speed_kmh) * 60, 1)

    return {
        "cell_speed_kmh": round(speed_kmh, 1),
        "approaching": approaching,
        "closing_speed_kmh": round(closing_speed_kmh, 1),
        "eta_minutes": eta_minutes,
    }


def run_once():
    now = datetime.now(timezone.utc)
    image = download_radar_image()

    Z, x_min, y_min, step, km_per_px = build_dbz_grid(image)
    rain_points = grid_to_points(Z, x_min, y_min, step)
    summary = summarize(rain_points, Z, km_per_px)
    shape_geojson = extract_shape_geojson(Z, x_min, y_min, step, km_per_px)

    prev_state = load_last_state()
    motion = None
    if summary and prev_state:
        prev_time = datetime.fromisoformat(prev_state["timestamp"])
        dt_seconds = (now - prev_time).total_seconds()
        motion = estimate_motion(prev_state, summary, dt_seconds)

    alert = False
    alert_message = None
    if summary:
        if summary["nearest_km"] <= config.ALERT_DISTANCE_KM:
            alert = True
            alert_message = f"ฝนอยู่ห่างออกไปเพียง {summary['nearest_km']} กม."
        if motion and motion.get("eta_minutes"):
            alert = True
            alert_message = (
                f"ฝนกำลังเคลื่อนเข้าหา คาดว่าจะถึงในประมาณ {motion['eta_minutes']} นาที "
                f"(ปัจจุบันห่าง {summary['nearest_km']} กม.)"
            )

    state = {
        "timestamp": now.isoformat(),
        "user_lat": config.USER_LAT,
        "user_lon": config.USER_LON,
        "summary": summary,
        "motion": motion,
        "alert": alert,
        "alert_message": alert_message,
        "rain_point_count": len(rain_points),
        "shape_geojson": shape_geojson,
    }
    save_state(state)
    return state


if __name__ == "__main__":
    result = run_once()
    # ไม่พิมพ์ shape_geojson เต็มๆ ในคอนโซล (ยาวเกินไป) แสดงแค่จำนวน feature
    printable = {k: v for k, v in result.items() if k != "shape_geojson"}
    printable["shape_feature_count"] = len(result["shape_geojson"]["features"])
    print(json.dumps(printable, ensure_ascii=False, indent=2))
    if result["alert"]:
        print("\n🌧️  แจ้งเตือน:", result["alert_message"])
    elif result["summary"] is None:
        print("\n✅ ไม่พบฝนในรัศมีที่ตรวจสอบ")
    else:
        print(f"\nℹ️  พบฝนแต่ยังไกล ({result['summary']['nearest_km']} กม.) ยังไม่ถึงเกณฑ์แจ้งเตือน")

