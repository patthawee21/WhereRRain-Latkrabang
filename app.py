"""
app.py — Flask server: รันการวิเคราะห์เป็นรอบๆ (background scheduler) และเปิด API
ให้หน้าเว็บ/แอปมือถือเรียกดูสถานะฝนล่าสุดได้
"""
import logging
from flask import Flask, jsonify, send_from_directory
from apscheduler.schedulers.background import BackgroundScheduler

import config
from analyzer import run_once, load_last_state

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("rain-alert")

app = Flask(__name__, static_folder="static")


def scheduled_job():
    try:
        state = run_once()
        if state["alert"]:
            log.info("ALERT: %s", state["alert_message"])
        else:
            log.info("ตรวจสอบแล้ว ไม่มีการแจ้งเตือน")
    except Exception as e:
        log.exception("การวิเคราะห์ล้มเหลว: %s", e)


@app.route("/")
def index():
    return send_from_directory("static", "index.html")


@app.route("/api/status")
def api_status():
    state = load_last_state()
    if state is None:
        return jsonify({"error": "ยังไม่มีข้อมูล กรุณารอรอบแรกของการวิเคราะห์"}), 202
    return jsonify(state)


@app.route("/api/refresh", methods=["POST"])
def api_refresh():
    """เรียกวิเคราะห์ทันที (เผื่อกดปุ่ม 'รีเฟรชตอนนี้' บนหน้าเว็บ)"""
    state = run_once()
    return jsonify(state)


if __name__ == "__main__":
    # รันวิเคราะห์ทันทีหนึ่งครั้งตอนสตาร์ท แล้วตั้งให้รันซ้ำทุก 10 นาที
    scheduled_job()
    scheduler = BackgroundScheduler()
    scheduler.add_job(scheduled_job, "interval", minutes=10, id="radar_poll")
    scheduler.start()

    app.run(host="0.0.0.0", port=5000, debug=False)
