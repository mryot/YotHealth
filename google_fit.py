"""
Google Fit REST API Client
===========================
อ่านข้อมูลสุขภาพจาก Google Fit API ด้วย OAuth2
รองรับ: ก้าวเดิน, อัตราการเต้นหัวใจ, การนอนหลับ,
         แคลอรี่, SpO2, ความดันโลหิต, น้ำหนัก, ระยะทาง

เอกสาร: https://developers.google.com/fit/rest/v1/reference
"""

from __future__ import annotations

import csv
import json
import os
import webbrowser
from datetime import datetime, timedelta
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any
from urllib.parse import parse_qs, urlencode, urlparse

import requests
from dotenv import load_dotenv

load_dotenv()

# ---------------------------------------------------------------------------
# ค่าคงที่
# ---------------------------------------------------------------------------

GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_FIT_BASE = "https://www.googleapis.com/fitness/v1/users/me"
TOKEN_FILE = ".google_token.json"

# OAuth2 Scopes
SCOPES = [
    "https://www.googleapis.com/auth/fitness.activity.read",
    "https://www.googleapis.com/auth/fitness.body.read",
    "https://www.googleapis.com/auth/fitness.heart_rate.read",
    "https://www.googleapis.com/auth/fitness.sleep.read",
    "https://www.googleapis.com/auth/fitness.blood_glucose.read",
    "https://www.googleapis.com/auth/fitness.blood_pressure.read",
    "https://www.googleapis.com/auth/fitness.oxygen_saturation.read",
    "https://www.googleapis.com/auth/fitness.reproductive_health.read",
]

# Data Type Names → Field mapping
DATA_TYPE_MAP: dict[str, dict] = {
    "steps": {
        "dataTypeName": "com.google.step_count.delta",
        "description": "ก้าวเดิน (Steps)",
        "field": "steps",
        "unit": "ก้าว",
        "aggregate": True,
    },
    "calories": {
        "dataTypeName": "com.google.calories.expended",
        "description": "แคลอรี่ที่เผาผลาญ (Calories)",
        "field": "calories",
        "unit": "kcal",
        "aggregate": True,
    },
    "distance": {
        "dataTypeName": "com.google.distance.delta",
        "description": "ระยะทาง (Distance)",
        "field": "distance",
        "unit": "เมตร",
        "aggregate": True,
    },
    "heart_rate": {
        "dataTypeName": "com.google.heart_rate.bpm",
        "description": "อัตราการเต้นหัวใจ (Heart Rate)",
        "field": "bpm",
        "unit": "bpm",
        "aggregate": False,
    },
    "active_minutes": {
        "dataTypeName": "com.google.active_minutes",
        "description": "นาทีออกกำลังกาย (Active Minutes)",
        "field": "duration",
        "unit": "นาที",
        "aggregate": True,
    },
    "move_minutes": {
        "dataTypeName": "com.google.heart_minutes",
        "description": "Heart Points",
        "field": "intensity",
        "unit": "คะแนน",
        "aggregate": True,
    },
    "weight": {
        "dataTypeName": "com.google.weight",
        "description": "น้ำหนัก (Weight)",
        "field": "weight",
        "unit": "kg",
        "aggregate": False,
    },
    "height": {
        "dataTypeName": "com.google.height",
        "description": "ส่วนสูง (Height)",
        "field": "height",
        "unit": "เมตร",
        "aggregate": False,
    },
    "body_fat": {
        "dataTypeName": "com.google.body.fat.percentage",
        "description": "เปอร์เซ็นต์ไขมัน (Body Fat %)",
        "field": "percentage",
        "unit": "%",
        "aggregate": False,
    },
    "spo2": {
        "dataTypeName": "com.google.oxygen_saturation",
        "description": "ออกซิเจนในเลือด (SpO2)",
        "field": "oxygen_saturation",
        "unit": "%",
        "aggregate": False,
    },
    "blood_pressure": {
        "dataTypeName": "com.google.blood_pressure",
        "description": "ความดันโลหิต (Blood Pressure)",
        "field": "blood_pressure_systolic",
        "unit": "mmHg",
        "aggregate": False,
    },
    "blood_glucose": {
        "dataTypeName": "com.google.blood_glucose",
        "description": "น้ำตาลในเลือด (Blood Glucose)",
        "field": "blood_glucose_level",
        "unit": "mmol/L",
        "aggregate": False,
    },
    "sleep": {
        "dataTypeName": "com.google.sleep.segment",
        "description": "การนอนหลับ (Sleep)",
        "field": "sleep_segment_type",
        "unit": "นาที",
        "aggregate": False,
    },
    "nutrition": {
        "dataTypeName": "com.google.nutrition",
        "description": "โภชนาการ (Nutrition)",
        "field": "calories",
        "unit": "kcal",
        "aggregate": False,
    },
}

SLEEP_STAGES: dict[int, str] = {
    1: "ตื่น (Awake)",
    2: "นอนหลับ (Sleep)",
    3: "Out of Bed",
    4: "หลับตื้น (Light Sleep)",
    5: "หลับ REM (REM Sleep)",
    6: "หลับลึก (Deep Sleep)",
}


# ---------------------------------------------------------------------------
# OAuth2 Flow
# ---------------------------------------------------------------------------

class _OAuthCallbackHandler(BaseHTTPRequestHandler):
    """รับ redirect callback จาก Google OAuth"""
    auth_code: str | None = None

    def do_GET(self) -> None:
        params = parse_qs(urlparse(self.path).query)
        if "code" in params:
            _OAuthCallbackHandler.auth_code = params["code"][0]
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(
                b"<html><body><h2>&#10003; Authorization successful!</h2>"
                b"<p>&#128994; &#3623;&#3636;&#3609;&#3604;&#3629;&#3623;&#3609;&#3637;&#3657;&#3648;&#3611;&#3636;&#3604;&#3652;&#3604;&#3657;</p></body></html>"
            )
        else:
            self.send_response(400)
            self.end_headers()

    def log_message(self, *args: Any) -> None:
        pass  # ปิด log


def _run_local_server(port: int = 8080) -> str | None:
    """เปิด HTTP server ชั่วคราวรับ authorization code"""
    server = HTTPServer(("localhost", port), _OAuthCallbackHandler)
    server.timeout = 120
    server.handle_request()
    return _OAuthCallbackHandler.auth_code


# ---------------------------------------------------------------------------
# Google Fit Client
# ---------------------------------------------------------------------------

class GoogleFitClient:
    """Client สำหรับ Google Fit REST API"""

    def __init__(
        self,
        client_id: str | None = None,
        client_secret: str | None = None,
        redirect_uri: str = "http://localhost:8080",
    ) -> None:
        self.client_id = client_id or os.getenv("GOOGLE_CLIENT_ID", "")
        self.client_secret = client_secret or os.getenv("GOOGLE_CLIENT_SECRET", "")
        self.redirect_uri = redirect_uri
        self._token: dict = {}
        self.session = requests.Session()

        # โหลด token ที่บันทึกไว้
        self._load_token()

    # ------------------------------------------------------------------
    # Token Management
    # ------------------------------------------------------------------

    def _load_token(self) -> None:
        if os.path.exists(TOKEN_FILE):
            with open(TOKEN_FILE, encoding="utf-8") as f:
                self._token = json.load(f)
            self._apply_token()

    def _save_token(self) -> None:
        with open(TOKEN_FILE, "w", encoding="utf-8") as f:
            json.dump(self._token, f, indent=2)

    def _apply_token(self) -> None:
        access_token = self._token.get("access_token", "")
        if access_token:
            self.session.headers.update({"Authorization": f"Bearer {access_token}"})

    def _refresh_token(self) -> None:
        """ต่ออายุ Access Token ด้วย Refresh Token"""
        refresh_token = self._token.get("refresh_token")
        if not refresh_token:
            raise RuntimeError("ไม่มี Refresh Token กรุณา authorize ใหม่")

        resp = requests.post(
            GOOGLE_TOKEN_URL,
            data={
                "client_id": self.client_id,
                "client_secret": self.client_secret,
                "refresh_token": refresh_token,
                "grant_type": "refresh_token",
            },
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
        self._token.update(data)
        self._save_token()
        self._apply_token()
        print("[✓] ต่ออายุ Access Token แล้ว")

    def is_authorized(self) -> bool:
        return bool(self._token.get("access_token") or self._token.get("refresh_token"))

    # ------------------------------------------------------------------
    # Authorization Flow
    # ------------------------------------------------------------------

    def authorize(self, port: int = 8080) -> None:
        """
        เปิดหน้า Google login ใน browser แล้วรับ authorization code
        อัตโนมัติผ่าน local redirect server
        """
        if not self.client_id or not self.client_secret:
            raise ValueError(
                "ไม่พบ GOOGLE_CLIENT_ID หรือ GOOGLE_CLIENT_SECRET\n"
                "กรุณาตั้งค่าใน .env หรือสร้าง OAuth2 credential ที่:\n"
                "https://console.cloud.google.com/apis/credentials"
            )

        params = {
            "client_id": self.client_id,
            "redirect_uri": f"http://localhost:{port}",
            "response_type": "code",
            "scope": " ".join(SCOPES),
            "access_type": "offline",
            "prompt": "consent",
        }
        auth_url = f"{GOOGLE_AUTH_URL}?{urlencode(params)}"

        print(f"\n[→] เปิดหน้า Google Login ใน browser...")
        print(f"    ถ้าไม่เปิดอัตโนมัติ คัดลอก URL นี้ไปวางใน browser:")
        print(f"    {auth_url}\n")
        webbrowser.open(auth_url)

        print(f"[⌛] รอการ authorize... (timeout 2 นาที)")
        code = _run_local_server(port)

        if not code:
            raise RuntimeError("ไม่ได้รับ authorization code กรุณาลองใหม่")

        # แลก code เป็น tokens
        resp = requests.post(
            GOOGLE_TOKEN_URL,
            data={
                "client_id": self.client_id,
                "client_secret": self.client_secret,
                "redirect_uri": f"http://localhost:{port}",
                "grant_type": "authorization_code",
                "code": code,
            },
            timeout=30,
        )
        resp.raise_for_status()
        self._token = resp.json()
        self._save_token()
        self._apply_token()
        print("[✓] Authorization สำเร็จ! บันทึก token แล้วที่", TOKEN_FILE)

    def ensure_authorized(self) -> None:
        """ตรวจสอบ token ถ้าหมดอายุให้ต่ออายุ ถ้าไม่มีให้ authorize ใหม่"""
        if not self.is_authorized():
            self.authorize()
            return

        # ลอง request ง่ายๆ เพื่อเช็ค token
        test = self.session.get(
            f"{GOOGLE_FIT_BASE}/dataSources",
            params={"limit": 1},
            timeout=10,
        )
        if test.status_code == 401:
            print("[!] Access Token หมดอายุ กำลังต่ออายุ...")
            self._refresh_token()

    # ------------------------------------------------------------------
    # Helper: เวลา
    # ------------------------------------------------------------------

    @staticmethod
    def _to_ns(dt: datetime) -> int:
        return int(dt.timestamp() * 1_000_000_000)

    @staticmethod
    def _from_ns(ns: int) -> datetime:
        return datetime.fromtimestamp(ns / 1_000_000_000)

    # ------------------------------------------------------------------
    # Core API Calls
    # ------------------------------------------------------------------

    def _aggregate(
        self,
        data_type_name: str,
        start_time: datetime,
        end_time: datetime,
        bucket_by_days: int = 1,
    ) -> list[dict]:
        """เรียก aggregate endpoint (สรุปรายวัน)"""
        url = f"{GOOGLE_FIT_BASE}/dataset:aggregate"
        payload = {
            "aggregateBy": [{"dataTypeName": data_type_name}],
            "bucketByTime": {"durationMillis": bucket_by_days * 86400 * 1000},
            "startTimeMillis": int(start_time.timestamp() * 1000),
            "endTimeMillis": int(end_time.timestamp() * 1000),
        }
        resp = self.session.post(url, json=payload, timeout=30)
        resp.raise_for_status()
        return resp.json().get("bucket", [])

    def _list_data_sources(self, data_type_name: str) -> list[str]:
        """หา data source IDs สำหรับ data type ที่กำหนด"""
        url = f"{GOOGLE_FIT_BASE}/dataSources"
        resp = self.session.get(
            url, params={"dataTypeName": data_type_name}, timeout=30
        )
        resp.raise_for_status()
        sources = resp.json().get("dataSource", [])
        return [s["dataStreamId"] for s in sources]

    def _get_dataset(
        self,
        data_source_id: str,
        start_time: datetime,
        end_time: datetime,
    ) -> list[dict]:
        """ดึงข้อมูล raw จาก data source"""
        start_ns = self._to_ns(start_time)
        end_ns = self._to_ns(end_time)
        dataset_id = f"{start_ns}-{end_ns}"
        url = f"{GOOGLE_FIT_BASE}/dataSources/{data_source_id}/datasets/{dataset_id}"
        resp = self.session.get(url, timeout=30)
        resp.raise_for_status()
        return resp.json().get("point", [])

    def _get_raw_data(
        self,
        data_type_name: str,
        start_time: datetime,
        end_time: datetime,
    ) -> list[dict]:
        """ดึงข้อมูล raw ทุก source ของ data type"""
        sources = self._list_data_sources(data_type_name)
        all_points: list[dict] = []
        for src in sources:
            try:
                pts = self._get_dataset(src, start_time, end_time)
                all_points.extend(pts)
            except requests.HTTPError:
                pass
        all_points.sort(key=lambda p: p.get("startTimeNanos", 0))
        return all_points

    # ------------------------------------------------------------------
    # ฟังก์ชันดึงข้อมูลแต่ละประเภท
    # ------------------------------------------------------------------

    def get_steps(self, start: datetime, end: datetime) -> list[dict]:
        """ก้าวเดินรายวัน"""
        buckets = self._aggregate("com.google.step_count.delta", start, end)
        return self._parse_aggregate_buckets(buckets, "steps", int)

    def get_calories(self, start: datetime, end: datetime) -> list[dict]:
        """แคลอรี่รายวัน"""
        buckets = self._aggregate("com.google.calories.expended", start, end)
        return self._parse_aggregate_buckets(buckets, "calories", float)

    def get_distance(self, start: datetime, end: datetime) -> list[dict]:
        """ระยะทางรายวัน (เมตร)"""
        buckets = self._aggregate("com.google.distance.delta", start, end)
        return self._parse_aggregate_buckets(buckets, "distance", float)

    def get_active_minutes(self, start: datetime, end: datetime) -> list[dict]:
        """นาทีออกกำลังกาย (Active Minutes)"""
        buckets = self._aggregate("com.google.active_minutes", start, end)
        return self._parse_aggregate_buckets(buckets, "duration", int)

    def get_heart_points(self, start: datetime, end: datetime) -> list[dict]:
        """Heart Points รายวัน"""
        buckets = self._aggregate("com.google.heart_minutes", start, end)
        return self._parse_aggregate_buckets(buckets, "intensity", float)

    def get_heart_rate(self, start: datetime, end: datetime) -> list[dict]:
        """Heart Rate ทุกจุดวัด"""
        points = self._get_raw_data("com.google.heart_rate.bpm", start, end)
        return self._parse_fp_field(points, "bpm")

    def get_weight(self, start: datetime, end: datetime) -> list[dict]:
        """น้ำหนัก (kg)"""
        points = self._get_raw_data("com.google.weight", start, end)
        return self._parse_fp_field(points, "weight")

    def get_height(self, start: datetime, end: datetime) -> list[dict]:
        """ส่วนสูง (เมตร)"""
        points = self._get_raw_data("com.google.height", start, end)
        return self._parse_fp_field(points, "height")

    def get_body_fat(self, start: datetime, end: datetime) -> list[dict]:
        """เปอร์เซ็นต์ไขมัน"""
        points = self._get_raw_data("com.google.body.fat.percentage", start, end)
        return self._parse_fp_field(points, "percentage")

    def get_spo2(self, start: datetime, end: datetime) -> list[dict]:
        """SpO2"""
        points = self._get_raw_data("com.google.oxygen_saturation", start, end)
        return self._parse_fp_field(points, "oxygen_saturation")

    def get_blood_pressure(self, start: datetime, end: datetime) -> list[dict]:
        """ความดันโลหิต"""
        points = self._get_raw_data("com.google.blood_pressure", start, end)
        result = []
        for p in points:
            ts = self._from_ns(int(p.get("startTimeNanos", 0)))
            row: dict[str, Any] = {"time": ts.strftime("%Y-%m-%d %H:%M:%S")}
            for val in p.get("value", []):
                fname = val.get("mapKey", "") or ""
                if "systolic" in fname:
                    row["systolic"] = round(val.get("value", {}).get("fpVal", 0), 1)
                elif "diastolic" in fname:
                    row["diastolic"] = round(val.get("value", {}).get("fpVal", 0), 1)
            # ลองแบบ list value
            if "systolic" not in row:
                vals = p.get("value", [])
                if len(vals) >= 2:
                    row["systolic"] = round(vals[0].get("fpVal", 0), 1)
                    row["diastolic"] = round(vals[1].get("fpVal", 0), 1)
            if "systolic" in row:
                result.append(row)
        return result

    def get_blood_glucose(self, start: datetime, end: datetime) -> list[dict]:
        """น้ำตาลในเลือด"""
        points = self._get_raw_data("com.google.blood_glucose", start, end)
        return self._parse_fp_field(points, "blood_glucose_level")

    def get_sleep(self, start: datetime, end: datetime) -> list[dict]:
        """การนอนหลับ (session ต่อ stage)"""
        # ดึงจาก sessions API
        url = f"{GOOGLE_FIT_BASE}/sessions"
        params = {
            "startTime": start.strftime("%Y-%m-%dT%H:%M:%S.000Z"),
            "endTime": end.strftime("%Y-%m-%dT%H:%M:%S.000Z"),
            "activityType": 72,  # Sleep
        }
        try:
            resp = self.session.get(url, params=params, timeout=30)
            resp.raise_for_status()
            sessions = resp.json().get("session", [])
        except requests.HTTPError:
            sessions = []

        # ดึง sleep segment ด้วย
        points = self._get_raw_data("com.google.sleep.segment", start, end)
        result = []
        for p in points:
            start_ns = int(p.get("startTimeNanos", 0))
            end_ns = int(p.get("endTimeNanos", start_ns))
            duration_min = round((end_ns - start_ns) / 60_000_000_000, 1)
            stage_id = int(p.get("value", [{}])[0].get("intVal", 2))
            result.append({
                "start_time": self._from_ns(start_ns).strftime("%Y-%m-%d %H:%M:%S"),
                "end_time": self._from_ns(end_ns).strftime("%Y-%m-%d %H:%M:%S"),
                "duration_min": duration_min,
                "stage_id": stage_id,
                "stage": SLEEP_STAGES.get(stage_id, f"ไม่ทราบ ({stage_id})"),
            })

        # ถ้าไม่มี segment ใช้ session แทน
        if not result and sessions:
            for s in sessions:
                start_ms = int(s.get("startTimeMillis", 0))
                end_ms = int(s.get("endTimeMillis", start_ms))
                result.append({
                    "start_time": datetime.fromtimestamp(start_ms / 1000).strftime("%Y-%m-%d %H:%M:%S"),
                    "end_time": datetime.fromtimestamp(end_ms / 1000).strftime("%Y-%m-%d %H:%M:%S"),
                    "duration_min": round((end_ms - start_ms) / 60000, 1),
                    "stage_id": 2,
                    "stage": "นอนหลับ (Sleep)",
                })
        return result

    def get_all_data(self, start: datetime, end: datetime) -> dict[str, list[dict]]:
        """ดึงข้อมูลสุขภาพทั้งหมด"""
        self.ensure_authorized()

        print(f"\n{'='*60}")
        print(f"ดึงข้อมูลสุขภาพจาก Google Fit")
        print(f"ช่วงเวลา: {start.strftime('%Y-%m-%d')} ถึง {end.strftime('%Y-%m-%d')}")
        print(f"{'='*60}\n")

        fetchers = {
            "steps": self.get_steps,
            "calories": self.get_calories,
            "distance": self.get_distance,
            "active_minutes": self.get_active_minutes,
            "heart_points": self.get_heart_points,
            "heart_rate": self.get_heart_rate,
            "weight": self.get_weight,
            "height": self.get_height,
            "body_fat": self.get_body_fat,
            "spo2": self.get_spo2,
            "blood_pressure": self.get_blood_pressure,
            "blood_glucose": self.get_blood_glucose,
            "sleep": self.get_sleep,
        }

        labels = {
            "steps": "ก้าวเดิน (Steps)",
            "calories": "แคลอรี่ (Calories)",
            "distance": "ระยะทาง (Distance)",
            "active_minutes": "นาทีออกกำลังกาย",
            "heart_points": "Heart Points",
            "heart_rate": "อัตราการเต้นหัวใจ",
            "weight": "น้ำหนัก (Weight)",
            "height": "ส่วนสูง (Height)",
            "body_fat": "เปอร์เซ็นต์ไขมัน",
            "spo2": "SpO2",
            "blood_pressure": "ความดันโลหิต",
            "blood_glucose": "น้ำตาลในเลือด",
            "sleep": "การนอนหลับ (Sleep)",
        }

        results: dict[str, list[dict]] = {}
        for name, fetcher in fetchers.items():
            try:
                records = fetcher(start, end)
                results[name] = records
                status = f"{len(records)} รายการ" if records else "ไม่มีข้อมูล"
                icon = "✓" if records else "–"
                print(f"[{icon}] {labels[name]}: {status}")
            except requests.HTTPError as e:
                code = e.response.status_code if e.response is not None else "?"
                print(f"[✗] {labels[name]}: HTTP {code}")
                results[name] = []
            except Exception as e:
                print(f"[✗] {labels[name]}: {e}")
                results[name] = []

        return results

    # ------------------------------------------------------------------
    # Parse Helpers
    # ------------------------------------------------------------------

    def _parse_aggregate_buckets(
        self,
        buckets: list[dict],
        field_name: str,
        cast: type = float,
    ) -> list[dict]:
        result = []
        for b in buckets:
            date = datetime.fromtimestamp(
                int(b.get("startTimeMillis", 0)) / 1000
            ).strftime("%Y-%m-%d")
            total = 0.0
            for ds in b.get("dataset", []):
                for pt in ds.get("point", []):
                    for val in pt.get("value", []):
                        total += val.get("fpVal") or val.get("intVal") or 0
            if total > 0:
                result.append({"date": date, "value": cast(round(total, 2))})
        return result

    def _parse_fp_field(self, points: list[dict], field_hint: str) -> list[dict]:
        result = []
        for p in points:
            ts = self._from_ns(int(p.get("startTimeNanos", 0)))
            vals = p.get("value", [])
            if not vals:
                continue
            v = vals[0].get("fpVal") or vals[0].get("intVal")
            if v is not None:
                result.append({
                    "time": ts.strftime("%Y-%m-%d %H:%M:%S"),
                    "value": round(float(v), 2),
                })
        return result


# ---------------------------------------------------------------------------
# แสดงผลและส่งออก
# ---------------------------------------------------------------------------

def summarize(data: dict[str, list[dict]]) -> None:
    print(f"\n{'='*60}")
    print("สรุปข้อมูลสุขภาพ")
    print(f"{'='*60}")

    if steps := data.get("steps"):
        total = sum(r["value"] for r in steps)
        avg = total / len(steps)
        print(f"  ก้าวเดินรวม         : {total:,.0f} ก้าว  (เฉลี่ย {avg:,.0f}/วัน)")

    if cals := data.get("calories"):
        total = sum(r["value"] for r in cals)
        print(f"  แคลอรี่รวม          : {total:,.1f} kcal  (เฉลี่ย {total/len(cals):,.1f}/วัน)")

    if dist := data.get("distance"):
        total = sum(r["value"] for r in dist) / 1000
        print(f"  ระยะทางรวม          : {total:,.2f} km")

    if am := data.get("active_minutes"):
        total = sum(r["value"] for r in am)
        print(f"  นาทีออกกำลังกาย     : {total:,.0f} นาที")

    if hr := data.get("heart_rate"):
        vals = [r["value"] for r in hr]
        print(f"  Heart Rate เฉลี่ย   : {sum(vals)/len(vals):.1f} bpm  (min: {min(vals):.0f}, max: {max(vals):.0f})")

    if w := data.get("weight"):
        latest = w[-1]["value"]
        print(f"  น้ำหนักล่าสุด       : {latest:.1f} kg")

    if bf := data.get("body_fat"):
        latest = bf[-1]["value"]
        print(f"  ไขมันล่าสุด         : {latest:.1f}%")

    if spo2 := data.get("spo2"):
        vals = [r["value"] for r in spo2]
        print(f"  SpO2 เฉลี่ย         : {sum(vals)/len(vals):.1f}%")

    if bp := data.get("blood_pressure"):
        latest = bp[-1]
        print(f"  ความดันล่าสุด       : {latest.get('systolic')}/{latest.get('diastolic')} mmHg")

    if sleep := data.get("sleep"):
        total = sum(r["duration_min"] for r in sleep)
        deep = sum(r["duration_min"] for r in sleep if r.get("stage_id") == 6)
        rem = sum(r["duration_min"] for r in sleep if r.get("stage_id") == 5)
        print(f"  นอนหลับรวม          : {total:.0f} นาที ({total/60:.1f} ชั่วโมง)")
        if deep:
            print(f"    - หลับลึก         : {deep:.0f} นาที")
        if rem:
            print(f"    - REM             : {rem:.0f} นาที")

    print()


def print_table(data: list[dict], title: str, unit: str = "", max_rows: int = 30) -> None:
    if not data:
        print(f"  (ไม่มีข้อมูล)\n")
        return
    print(f"\n--- {title} ---")
    headers = list(data[0].keys())
    widths = {h: max(len(h), max(len(str(r.get(h, ""))) for r in data)) for h in headers}
    header_line = "  ".join(str(h).ljust(widths[h]) for h in headers)
    if unit:
        header_line += f"  (หน่วย: {unit})"
    print(header_line)
    print("-" * len(header_line))
    for row in data[:max_rows]:
        print("  ".join(str(row.get(h, "")).ljust(widths[h]) for h in headers))
    if len(data) > max_rows:
        print(f"  ... และอีก {len(data) - max_rows} รายการ")
    print()


def export_to_csv(data: dict[str, list[dict]], output_dir: str = "health_export") -> None:
    os.makedirs(output_dir, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    for name, records in data.items():
        if not records:
            continue
        path = os.path.join(output_dir, f"gfit_{name}_{ts}.csv")
        with open(path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=list(records[0].keys()))
            writer.writeheader()
            writer.writerows(records)
        print(f"  [✓] {name} → {path} ({len(records)} รายการ)")


def export_to_json(data: dict[str, list[dict]], filepath: str | None = None) -> None:
    if not filepath:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        os.makedirs("health_export", exist_ok=True)
        filepath = f"health_export/gfit_data_{ts}.json"
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"\n[✓] บันทึกทั้งหมด → {filepath}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(
        description="ดึงข้อมูลสุขภาพจาก Google Fit API",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
ตัวอย่าง:
  python google_fit.py                     # ดึงข้อมูล 7 วันล่าสุด
  python google_fit.py --days 30           # ดึงข้อมูล 30 วันล่าสุด
  python google_fit.py --start 2025-01-01  # กำหนดวันเริ่มต้น
  python google_fit.py --auth              # บังคับ authorize ใหม่
  python google_fit.py --export csv        # ส่งออก CSV
  python google_fit.py --export json       # ส่งออก JSON
  python google_fit.py --export both --verbose
        """,
    )
    parser.add_argument("--start", type=str, help="วันเริ่มต้น YYYY-MM-DD")
    parser.add_argument("--end", type=str, help="วันสิ้นสุด YYYY-MM-DD")
    parser.add_argument("--days", type=int, default=7, help="จำนวนวันย้อนหลัง (default: 7)")
    parser.add_argument("--auth", action="store_true", help="บังคับ authorize ใหม่")
    parser.add_argument("--port", type=int, default=8080, help="port สำหรับ OAuth2 callback (default: 8080)")
    parser.add_argument("--export", choices=["csv", "json", "both", "none"], default="none")
    parser.add_argument("--verbose", action="store_true", help="แสดงรายละเอียดข้อมูล")
    args = parser.parse_args()

    end_time = datetime.now().replace(hour=23, minute=59, second=59, microsecond=0)
    if args.end:
        end_time = datetime.strptime(args.end, "%Y-%m-%d").replace(hour=23, minute=59, second=59)

    if args.start:
        start_time = datetime.strptime(args.start, "%Y-%m-%d")
    else:
        start_time = (end_time - timedelta(days=args.days)).replace(
            hour=0, minute=0, second=0, microsecond=0
        )

    client = GoogleFitClient()

    # บังคับ authorize ใหม่
    if args.auth or not client.is_authorized():
        client.authorize(port=args.port)
    else:
        client.ensure_authorized()

    # ดึงข้อมูล
    data = client.get_all_data(start_time, end_time)

    # สรุป
    summarize(data)

    # แสดงรายละเอียด
    if args.verbose:
        label_unit = {
            "steps":          ("ก้าวเดิน (Steps)",         "ก้าว/วัน"),
            "calories":       ("แคลอรี่ (Calories)",        "kcal/วัน"),
            "distance":       ("ระยะทาง (Distance)",        "เมตร/วัน"),
            "active_minutes": ("นาทีออกกำลังกาย",           "นาที/วัน"),
            "heart_points":   ("Heart Points",              "คะแนน/วัน"),
            "heart_rate":     ("Heart Rate",                "bpm"),
            "weight":         ("น้ำหนัก (Weight)",          "kg"),
            "height":         ("ส่วนสูง (Height)",          "เมตร"),
            "body_fat":       ("เปอร์เซ็นต์ไขมัน",          "%"),
            "spo2":           ("SpO2",                     "%"),
            "blood_pressure": ("ความดันโลหิต",              "mmHg"),
            "blood_glucose":  ("น้ำตาลในเลือด",             "mmol/L"),
            "sleep":          ("การนอนหลับ",               "นาที"),
        }
        print(f"\n{'='*60}")
        print("รายละเอียดข้อมูล")
        print(f"{'='*60}")
        for key, (title, unit) in label_unit.items():
            print_table(data.get(key, []), title, unit)

    # ส่งออก
    if args.export in ("csv", "both"):
        print("\nส่งออก CSV:")
        export_to_csv(data)
    if args.export in ("json", "both"):
        export_to_json(data)


if __name__ == "__main__":
    main()
