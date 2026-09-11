"""
geo.py — แปลงพิกเซล <-> lat/lon และแปลงสี -> ค่า dBZ
"""
import numpy as np
from config import CONTROL_POINTS, LEGEND_TABLE


class Georeferencer:
    """
    หาสมการ affine transform: [lat, lon] = A * [px, py, 1]
    จากจุดอ้างอิง (control points) อย่างน้อย 3 จุด (แนะนำ >= 4 จุด)
    ใช้ least-squares เพื่อลดผลกระทบจากความคลาดเคลื่อนของแต่ละจุด
    """

    def __init__(self, control_points=None):
        cps = control_points or CONTROL_POINTS
        if len(cps) < 3:
            raise ValueError("ต้องมี control points อย่างน้อย 3 จุดสำหรับ georeferencing")

        px = np.array([[p[0], p[1], 1.0] for p in cps])   # N x 3
        lat = np.array([p[2] for p in cps])
        lon = np.array([p[3] for p in cps])

        # แก้สมการ least-squares: px @ coef = lat  (และเช่นเดียวกันสำหรับ lon)
        self.coef_lat, *_ = np.linalg.lstsq(px, lat, rcond=None)
        self.coef_lon, *_ = np.linalg.lstsq(px, lon, rcond=None)

        # เก็บ transform ผกผัน (lat/lon -> pixel) ด้วยวิธีเดียวกัน (สลับตัวแปร)
        latlon = np.array([[p[2], p[3], 1.0] for p in cps])
        pxs = np.array([p[0] for p in cps])
        pys = np.array([p[1] for p in cps])
        self.coef_px, *_ = np.linalg.lstsq(latlon, pxs, rcond=None)
        self.coef_py, *_ = np.linalg.lstsq(latlon, pys, rcond=None)

        # ประมาณ km ต่อพิกเซล (ใช้สำหรับคำนวณระยะทาง/ความเร็วคร่าวๆ)
        self._km_per_deg_lat = 111.0
        self._km_per_deg_lon = 111.0 * np.cos(np.radians(np.mean(lat)))

    def pixel_to_latlon(self, px, py):
        vec = np.array([px, py, 1.0])
        lat = float(self.coef_lat @ vec)
        lon = float(self.coef_lon @ vec)
        return lat, lon

    def latlon_to_pixel(self, lat, lon):
        vec = np.array([lat, lon, 1.0])
        px = float(self.coef_px @ vec)
        py = float(self.coef_py @ vec)
        return px, py

    def km_between(self, latlon1, latlon2):
        """ระยะทางประมาณแบบ haversine (แม่นกว่า flat-earth เมื่อระยะไกล)"""
        lat1, lon1 = latlon1
        lat2, lon2 = latlon2
        R = 6371.0
        p1, p2 = np.radians(lat1), np.radians(lat2)
        dphi = np.radians(lat2 - lat1)
        dlmb = np.radians(lon2 - lon1)
        a = np.sin(dphi / 2) ** 2 + np.cos(p1) * np.cos(p2) * np.sin(dlmb / 2) ** 2
        return 2 * R * np.arcsin(np.sqrt(a))


def color_to_dbz(rgb, tolerance_max=45, min_saturation=40):
    """
    แปลงสี RGB ที่อ่านได้จากภาพเรดาร์ -> ค่า dBZ โดยเทียบกับ LEGEND_TABLE
    (nearest-color matching) คืนค่า None ถ้าสีไม่ใกล้เคียงสีในตารางเลย
    (แปลว่าจุดนั้นน่าจะเป็นพื้นหลัง/ขอบเขต/ตัวหนังสือ ไม่ใช่ฝน)

    min_saturation: สีของฝนบนเรดาร์เป็นสีสดเสมอ (ไม่ใช่โทนเทา/น้ำตาลของพื้นแผนที่)
    จึงกรองพิกเซลที่ "ใกล้เฉดเทา" ออกก่อน เพื่อไม่ให้พื้นหลัง/ภูมิประเทศ/เส้นขอบ
    ถูกจับเป็นฝนผิดๆ (false positive) — ค่ายิ่งสูงยิ่งกรองเข้ม
    """
    r, g, b = rgb
    if max(r, g, b) - min(r, g, b) < min_saturation:
        return None

    best_dbz, best_dist = None, float("inf")
    for dbz, (lr, lg, lb) in LEGEND_TABLE:
        dist = (r - lr) ** 2 + (g - lg) ** 2 + (b - lb) ** 2
        if dist < best_dist:
            best_dist = dist
            best_dbz = dbz
    if best_dist ** 0.5 > tolerance_max:
        return None
    return best_dbz
