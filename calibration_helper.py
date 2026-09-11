"""
calibration_helper.py
======================
สคริปต์ช่วย "หาพิกเซล" ของจุดอ้างอิงในภาพเรดาร์ เพื่อใช้กรอกลงใน CONTROL_POINTS
(config.py)

วิธีใช้:
1. รัน:  python3 calibration_helper.py path/to/radar_image.jpg
2. เปิดไฟล์ที่ได้ (calibration_grid.png) ดูเส้นกริดสีแดงทุก 50 พิกเซล พร้อมตัวเลขกำกับ
3. หาตำแหน่งของจุดที่รู้พิกัดจริงแน่นอน เช่น ชื่อจังหวัด/อำเภอที่ระบุในภาพ
   (แนะนำให้ใช้จุดตัดถนน/ปากแม่น้ำ/ตัวเมืองแทนตำแหน่งตัวหนังสือ เพราะตัวหนังสือ
   มักไม่ได้วางอยู่ตรงจุดพิกัดพอดี — ให้อ้างอิงจากตำแหน่ง "ตัวเมือง" จริงแทน)
4. เปิด Google Maps หาพิกัด lat/lon จริงของจุดนั้น
5. นำคู่ (พิกเซล x, พิกเซล y, lat, lon) ไปใส่ใน CONTROL_POINTS ที่ config.py
   ทำซ้ำอย่างน้อย 4-5 จุด กระจายรอบภาพ (อย่ากระจุกอยู่มุมเดียว) เพื่อความแม่นยำ
"""
import sys
from PIL import Image, ImageDraw

def make_grid(image_path, out_path="calibration_grid.png", step=50):
    im = Image.open(image_path).convert("RGB")
    draw = ImageDraw.Draw(im)
    w, h = im.size

    for x in range(0, w, step):
        draw.line([(x, 0), (x, h)], fill=(255, 0, 0), width=1)
        draw.text((x + 2, 2), str(x), fill=(255, 0, 0))
    for y in range(0, h, step):
        draw.line([(0, y), (w, y)], fill=(255, 0, 0), width=1)
        draw.text((2, y + 2), str(y), fill=(255, 0, 0))

    im.save(out_path)
    print(f"บันทึกภาพกริดที่: {out_path}  (ขนาดภาพ {w}x{h}, เส้นกริดทุก {step}px)")
    print("เปิดไฟล์นี้ดู แล้วอ่านพิกัด (x,y) ของจุดอ้างอิงที่รู้ lat/lon จริง")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("การใช้งาน: python3 calibration_helper.py <path หรือ URL ของภาพเรดาร์>")
        sys.exit(1)
    make_grid(sys.argv[1])
