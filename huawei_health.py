"""
HUAWEI Health Kit REST API Client
===================================
อ่านข้อมูลสุขภาพจาก HUAWEI Health Kit API
รองรับ: ก้าวเดิน, อัตราการเต้นของหัวใจ, การนอนหลับ,
         แคลอรี่, SpO2, ความดันโลหิต, น้ำหนัก, ออกกำลังกาย

เอกสาร: https://developer.huawei.com/consumer/en/doc/HMSCore-Guides/health-overview-0000001055038982
"""

from __future__ import annotations

import csv
import json
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from typing import Any

import requests
from dotenv import load_dotenv

# ---------------------------------------------------------------------------
# โหลด environment variables
# ---------------------------------------------------------------------------
load_dotenv()

# ---------------------------------------------------------------------------
# ค่าคงที่ของ API
# ---------------------------------------------------------------------------

# Endpoint สำหรับแต่ละภูมิภาค
REGION_ENDPOINTS: dict[str, str] = {
    "CN": "https://healthkit-store.cloud.huawei.com",
    "EU": "https://healthkit-store.cloud.huawei.eu",
    "AS": "https://healthkit-store.cloud.huawei.asia",
    "RU": "https://healthkit-store.cloud.huawei.ru",
}

OAUTH_TOKEN_URL = "https://oauth-login.cloud.huawei.com/oauth2/v3/token"

# Data Type ที่รองรับ
DATA_TYPES: dict[str, dict[str, str]] = {
    "steps": {
        "dataTypeName": "com.huawei.continuous.steps.total",
        "description": "ก้าวเดิน (Steps)",
        "field": "steps",
        "unit": "ครั้ง",
    },
    "heart_rate": {
        "dataTypeName": "com.huawei.continuous.heart_rate.statistics",
        "description": "อัตราการเต้นของหัวใจ (Heart Rate)",
        "field": "bpm",
        "unit": "bpm",
    },
    "calories": {
        "dataTypeName": "com.huawei.continuous.calories.total",
        "description": "แคลอรี่ที่เผาผลาญ (Calories)",
        "field": "calories",
        "unit": "kcal",
    },
    "spo2": {
        "dataTypeName": "com.huawei.continuous.spo2.statistics",
        "description": "ออกซิเจนในเลือด (SpO2)",
        "field": "saturation",
        "unit": "%",
    },
    "sleep": {
        "dataTypeName": "com.huawei.sleep.stage.statistics",
        "description": "การนอนหลับ (Sleep)",
        "field": "sleep_type",
        "unit": "นาที",
    },
    "blood_pressure": {
        "dataTypeName": "com.huawei.instantaneous.blood_pressure",
        "description": "ความดันโลหิต (Blood Pressure)",
        "field": "systolic",
        "unit": "mmHg",
    },
    "weight": {
        "dataTypeName": "com.huawei.instantaneous.body.weight",
        "description": "น้ำหนักร่างกาย (Weight)",
        "field": "body_weight",
        "unit": "kg",
    },
    "stress": {
        "dataTypeName": "com.huawei.continuous.stress.statistics",
        "description": "ระดับความเครียด (Stress)",
        "field": "stress_avg",
        "unit": "คะแนน",
    },
    "distance": {
        "dataTypeName": "com.huawei.continuous.distance.total",
        "description": "ระยะทาง (Distance)",
        "field": "distance",
        "unit": "เมตร",
    },
    "activity": {
        "dataTypeName": "com.huawei.continuous.activity.summary",
        "description": "สรุปกิจกรรม (Activity Summary)",
        "field": "activity_type",
        "unit": "",
    },
}

# สถานะการนอนหลับ
SLEEP_STAGES: dict[int, str] = {
    1: "หลับตื้น (Light Sleep)",
    2: "หลับลึก (Deep Sleep)",
    3: "หลับ REM (REM Sleep)",
    4: "ตื่น (Awake)",
    5: "กำลังจะหลับ (Falling Asleep)",
}


# ---------------------------------------------------------------------------
# คลาสหลัก
# ---------------------------------------------------------------------------

class HuaweiHealthClient:
    """Client สำหรับ HUAWEI Health Kit REST API"""

    def __init__(
        self,
        client_id: str | None = None,
        client_secret: str | None = None,
        access_token: str | None = None,
        region: str | None = None,
    ) -> None:
        self.client_id = client_id or os.getenv("HUAWEI_CLIENT_ID", "")
        self.client_secret = client_secret or os.getenv("HUAWEI_CLIENT_SECRET", "")
        self.region = (region or os.getenv("HUAWEI_API_REGION", "EU")).upper()
        self._access_token = access_token or os.getenv("HUAWEI_ACCESS_TOKEN", "")
        # ถ้ามี access token อยู่แล้ว ให้ถือว่ายังใช้ได้ (1 ชั่วโมง)
        self._token_expires_at: float = time.time() + 3600 if self._access_token else 0.0

        base = REGION_ENDPOINTS.get(self.region, REGION_ENDPOINTS["EU"])
        self.base_url = f"{base}/healthkit/v1"

        self.session = requests.Session()
        self.session.headers.update({"Content-Type": "application/json"})
        if self._access_token:
            self.session.headers.update({"Authorization": f"Bearer {self._access_token}"})

    # ------------------------------------------------------------------
    # Authentication
    # ------------------------------------------------------------------

    def get_access_token(self) -> str:
        """
        ขอ Access Token ด้วย Client Credentials Grant
        (สำหรับ server-to-server ไม่ต้องการ user login)
        """
        # ถ้า token ยังไม่หมดอายุ ใช้ token เดิม
        if self._access_token and time.time() < self._token_expires_at:
            return self._access_token

        # ถ้าไม่มี client_secret แต่มี access_token → ใช้ token ที่มีต่อไป (อาจหมดอายุแล้ว)
        if self._access_token and not self.client_secret:
            print("[!] Access Token อาจหมดอายุแล้ว กรุณาต่ออายุ token ใน .env")
            return self._access_token

        if not self.client_id or not self.client_secret:
            raise ValueError(
                "ไม่พบ client_id หรือ client_secret\n"
                "กรุณาตั้งค่า HUAWEI_CLIENT_ID และ HUAWEI_CLIENT_SECRET ใน .env"
            )

        payload = {
            "grant_type": "client_credentials",
            "client_id": self.client_id,
            "client_secret": self.client_secret,
        }
        resp = requests.post(
            OAUTH_TOKEN_URL,
            data=payload,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()

        self._access_token = data["access_token"]
        self._token_expires_at = time.time() + int(data.get("expires_in", 3600)) - 60
        self.session.headers.update({"Authorization": f"Bearer {self._access_token}"})
        print(f"[✓] ได้รับ Access Token แล้ว (หมดอายุใน {data.get('expires_in', 3600)} วินาที)")
        return self._access_token

    def set_access_token(self, token: str) -> None:
        """ตั้งค่า Access Token โดยตรง (จาก OAuth Authorization Code Flow)"""
        self._access_token = token
        self._token_expires_at = time.time() + 3600
        self.session.headers.update({"Authorization": f"Bearer {token}"})

    # ------------------------------------------------------------------
    # Helper: แปลงเวลา
    # ------------------------------------------------------------------

    @staticmethod
    def _to_ns(dt: datetime) -> int:
        """แปลง datetime เป็น nanoseconds (Unix epoch)"""
        return int(dt.timestamp() * 1_000_000_000)

    @staticmethod
    def _from_ns(ns: int) -> datetime:
        """แปลง nanoseconds กลับเป็น datetime (local timezone)"""
        return datetime.fromtimestamp(ns / 1_000_000_000)

    # ------------------------------------------------------------------
    # Query APIs
    # ------------------------------------------------------------------

    def query_sample_data(
        self,
        data_type_name: str,
        start_time: datetime,
        end_time: datetime,
        page_size: int = 100,
    ) -> list[dict]:
        """ดึงข้อมูล sample แบบ raw ช่วงเวลาที่กำหนด"""
        self.get_access_token()

        url = f"{self.base_url}/querier/sample-data"
        payload = {
            "dataTypeName": data_type_name,
            "startTime": self._to_ns(start_time),
            "endTime": self._to_ns(end_time),
            "pageSize": page_size,
        }

        all_records: list[dict] = []
        page_token: str | None = None

        while True:
            if page_token:
                payload["pageToken"] = page_token

            resp = self.session.post(url, json=payload, timeout=30)
            resp.raise_for_status()
            data = resp.json()

            records = data.get("samplePoints", [])
            all_records.extend(records)

            page_token = data.get("nextPageToken")
            if not page_token:
                break

        return all_records

    def query_aggregate_data(
        self,
        data_type_name: str,
        start_time: datetime,
        end_time: datetime,
        interval_seconds: int = 86400,  # default 1 วัน
    ) -> list[dict]:
        """ดึงข้อมูลสรุปรวม (aggregate) ตามช่วงเวลา"""
        self.get_access_token()

        url = f"{self.base_url}/querier/aggregate-data"
        payload = {
            "dataTypeName": data_type_name,
            "startTime": self._to_ns(start_time),
            "endTime": self._to_ns(end_time),
            "bucketByTime": {
                "duration": interval_seconds * 1_000_000_000,  # nanoseconds
            },
        }

        resp = self.session.post(url, json=payload, timeout=30)
        resp.raise_for_status()
        return resp.json().get("buckets", [])

    # ------------------------------------------------------------------
    # ฟังก์ชันดึงข้อมูลแต่ละประเภท
    # ------------------------------------------------------------------

    def get_steps(
        self,
        start_time: datetime,
        end_time: datetime,
        aggregate: bool = True,
    ) -> list[dict]:
        """ดึงข้อมูลก้าวเดิน"""
        dtype = DATA_TYPES["steps"]["dataTypeName"]
        if aggregate:
            buckets = self.query_aggregate_data(dtype, start_time, end_time)
            return self._parse_aggregate(buckets, "steps")
        return self.query_sample_data(dtype, start_time, end_time)

    def get_heart_rate(
        self,
        start_time: datetime,
        end_time: datetime,
        aggregate: bool = True,
    ) -> list[dict]:
        """ดึงข้อมูลอัตราการเต้นของหัวใจ"""
        dtype = DATA_TYPES["heart_rate"]["dataTypeName"]
        if aggregate:
            buckets = self.query_aggregate_data(dtype, start_time, end_time, interval_seconds=3600)
            return self._parse_aggregate(buckets, "bpm")
        return self.query_sample_data(dtype, start_time, end_time)

    def get_sleep(
        self,
        start_time: datetime,
        end_time: datetime,
    ) -> list[dict]:
        """ดึงข้อมูลการนอนหลับ"""
        dtype = DATA_TYPES["sleep"]["dataTypeName"]
        records = self.query_sample_data(dtype, start_time, end_time)
        return self._parse_sleep(records)

    def get_calories(
        self,
        start_time: datetime,
        end_time: datetime,
        aggregate: bool = True,
    ) -> list[dict]:
        """ดึงข้อมูลแคลอรี่"""
        dtype = DATA_TYPES["calories"]["dataTypeName"]
        if aggregate:
            buckets = self.query_aggregate_data(dtype, start_time, end_time)
            return self._parse_aggregate(buckets, "calories")
        return self.query_sample_data(dtype, start_time, end_time)

    def get_spo2(
        self,
        start_time: datetime,
        end_time: datetime,
    ) -> list[dict]:
        """ดึงข้อมูล SpO2"""
        dtype = DATA_TYPES["spo2"]["dataTypeName"]
        records = self.query_sample_data(dtype, start_time, end_time)
        return self._parse_records(records, "saturation")

    def get_blood_pressure(
        self,
        start_time: datetime,
        end_time: datetime,
    ) -> list[dict]:
        """ดึงข้อมูลความดันโลหิต"""
        dtype = DATA_TYPES["blood_pressure"]["dataTypeName"]
        records = self.query_sample_data(dtype, start_time, end_time)
        return self._parse_blood_pressure(records)

    def get_weight(
        self,
        start_time: datetime,
        end_time: datetime,
    ) -> list[dict]:
        """ดึงข้อมูลน้ำหนัก"""
        dtype = DATA_TYPES["weight"]["dataTypeName"]
        records = self.query_sample_data(dtype, start_time, end_time)
        return self._parse_records(records, "body_weight")

    def get_stress(
        self,
        start_time: datetime,
        end_time: datetime,
    ) -> list[dict]:
        """ดึงข้อมูลระดับความเครียด"""
        dtype = DATA_TYPES["stress"]["dataTypeName"]
        records = self.query_sample_data(dtype, start_time, end_time)
        return self._parse_records(records, "stress_avg")

    def get_distance(
        self,
        start_time: datetime,
        end_time: datetime,
        aggregate: bool = True,
    ) -> list[dict]:
        """ดึงข้อมูลระยะทาง"""
        dtype = DATA_TYPES["distance"]["dataTypeName"]
        if aggregate:
            buckets = self.query_aggregate_data(dtype, start_time, end_time)
            return self._parse_aggregate(buckets, "distance")
        return self.query_sample_data(dtype, start_time, end_time)

    def get_all_data(
        self,
        start_time: datetime,
        end_time: datetime,
    ) -> dict[str, list[dict]]:
        """ดึงข้อมูลสุขภาพทั้งหมด"""
        print(f"\n{'='*60}")
        print(f"ดึงข้อมูลสุขภาพจาก HUAWEI Health")
        print(f"ช่วงเวลา: {start_time.strftime('%Y-%m-%d %H:%M')} ถึง {end_time.strftime('%Y-%m-%d %H:%M')}")
        print(f"{'='*60}\n")

        fetchers = {
            "steps": self.get_steps,
            "heart_rate": self.get_heart_rate,
            "calories": self.get_calories,
            "sleep": self.get_sleep,
            "spo2": self.get_spo2,
            "blood_pressure": self.get_blood_pressure,
            "weight": self.get_weight,
            "stress": self.get_stress,
            "distance": self.get_distance,
        }

        results: dict[str, list[dict]] = {}
        for name, fetcher in fetchers.items():
            info = DATA_TYPES[name]
            try:
                if name in ("steps", "heart_rate", "calories", "distance"):
                    records = fetcher(start_time, end_time)
                else:
                    records = fetcher(start_time, end_time)
                results[name] = records
                print(f"[✓] {info['description']}: {len(records)} รายการ")
            except requests.HTTPError as e:
                if e.response is not None and e.response.status_code in (403, 404):
                    print(f"[–] {info['description']}: ไม่มีสิทธิ์หรือไม่มีข้อมูล")
                else:
                    print(f"[✗] {info['description']}: ข้อผิดพลาด - {e}")
                results[name] = []
            except Exception as e:
                print(f"[✗] {info['description']}: {e}")
                results[name] = []

        return results

    # ------------------------------------------------------------------
    # Parse Helpers
    # ------------------------------------------------------------------

    def _parse_aggregate(self, buckets: list[dict], field: str) -> list[dict]:
        """แปลง aggregate bucket เป็น list ของ dict"""
        result = []
        for bucket in buckets:
            start_ns = bucket.get("startTime", 0)
            end_ns = bucket.get("endTime", 0)
            for dataset in bucket.get("dataset", []):
                for point in dataset.get("samplePoints", []):
                    row: dict[str, Any] = {
                        "start_time": self._from_ns(start_ns).strftime("%Y-%m-%d %H:%M:%S"),
                        "end_time": self._from_ns(end_ns).strftime("%Y-%m-%d %H:%M:%S"),
                    }
                    for val in point.get("value", []):
                        if val.get("fieldName") == field:
                            row["value"] = val.get("intVal") or val.get("doubleVal") or 0
                    if "value" in row:
                        result.append(row)
        return result

    def _parse_records(self, records: list[dict], field: str) -> list[dict]:
        """แปลง sample records เป็น list ของ dict สำหรับ field เดียว"""
        result = []
        for point in records:
            ts_ns = point.get("startTime", 0)
            row: dict[str, Any] = {
                "time": self._from_ns(ts_ns).strftime("%Y-%m-%d %H:%M:%S"),
            }
            for val in point.get("value", []):
                if val.get("fieldName") == field:
                    row["value"] = val.get("intVal") or val.get("doubleVal") or 0
            if "value" in row:
                result.append(row)
        return result

    def _parse_blood_pressure(self, records: list[dict]) -> list[dict]:
        """แปลงข้อมูลความดันโลหิต (systolic + diastolic)"""
        result = []
        for point in records:
            ts_ns = point.get("startTime", 0)
            row: dict[str, Any] = {
                "time": self._from_ns(ts_ns).strftime("%Y-%m-%d %H:%M:%S"),
            }
            for val in point.get("value", []):
                fname = val.get("fieldName", "")
                v = val.get("intVal") or val.get("doubleVal") or 0
                if fname == "systolic":
                    row["systolic"] = v
                elif fname == "diastolic":
                    row["diastolic"] = v
            if "systolic" in row:
                result.append(row)
        return result

    def _parse_sleep(self, records: list[dict]) -> list[dict]:
        """แปลงข้อมูลการนอนหลับพร้อมชื่อ stage"""
        result = []
        for point in records:
            start_ns = point.get("startTime", 0)
            end_ns = point.get("endTime", start_ns)
            row: dict[str, Any] = {
                "start_time": self._from_ns(start_ns).strftime("%Y-%m-%d %H:%M:%S"),
                "end_time": self._from_ns(end_ns).strftime("%Y-%m-%d %H:%M:%S"),
                "duration_min": round((end_ns - start_ns) / 60_000_000_000, 1),
            }
            for val in point.get("value", []):
                if val.get("fieldName") == "sleep_type":
                    stage_id = int(val.get("intVal", 0))
                    row["stage_id"] = stage_id
                    row["stage"] = SLEEP_STAGES.get(stage_id, f"ไม่ทราบ ({stage_id})")
            if "stage" in row:
                result.append(row)
        return result


# ---------------------------------------------------------------------------
# แสดงผล
# ---------------------------------------------------------------------------

def print_table(data: list[dict], title: str, unit: str = "") -> None:
    """แสดงข้อมูลในรูปแบบตาราง"""
    if not data:
        print(f"  (ไม่มีข้อมูล)\n")
        return

    print(f"\n--- {title} ---")
    if not data:
        return

    headers = list(data[0].keys())
    col_widths = {h: max(len(str(h)), max(len(str(row.get(h, ""))) for row in data)) for h in headers}

    header_line = "  ".join(str(h).ljust(col_widths[h]) for h in headers)
    if unit:
        header_line += f"  (หน่วย: {unit})"
    print(header_line)
    print("-" * len(header_line))

    for row in data[:50]:  # แสดงสูงสุด 50 แถว
        print("  ".join(str(row.get(h, "")).ljust(col_widths[h]) for h in headers))

    if len(data) > 50:
        print(f"  ... และอีก {len(data) - 50} รายการ")
    print()


def summarize(data: dict[str, list[dict]]) -> None:
    """สรุปผลรวมข้อมูลสุขภาพ"""
    print(f"\n{'='*60}")
    print("สรุปข้อมูลสุขภาพ")
    print(f"{'='*60}")

    # ก้าวเดิน
    steps_data = data.get("steps", [])
    if steps_data:
        total_steps = sum(r.get("value", 0) for r in steps_data)
        print(f"  ก้าวเดินรวม      : {total_steps:,.0f} ก้าว")

    # แคลอรี่
    cal_data = data.get("calories", [])
    if cal_data:
        total_cal = sum(r.get("value", 0) for r in cal_data)
        print(f"  แคลอรี่รวม       : {total_cal:,.1f} kcal")

    # ระยะทาง
    dist_data = data.get("distance", [])
    if dist_data:
        total_dist = sum(r.get("value", 0) for r in dist_data)
        print(f"  ระยะทางรวม       : {total_dist/1000:,.2f} km")

    # อัตราการเต้นหัวใจ
    hr_data = data.get("heart_rate", [])
    if hr_data:
        values = [r.get("value", 0) for r in hr_data if r.get("value")]
        if values:
            print(f"  Heart Rate เฉลี่ย: {sum(values)/len(values):.1f} bpm  (min: {min(values)}, max: {max(values)})")

    # SpO2
    spo2_data = data.get("spo2", [])
    if spo2_data:
        values = [r.get("value", 0) for r in spo2_data if r.get("value")]
        if values:
            print(f"  SpO2 เฉลี่ย      : {sum(values)/len(values):.1f}%  (min: {min(values)}%, max: {max(values)}%)")

    # การนอนหลับ
    sleep_data = data.get("sleep", [])
    if sleep_data:
        total_sleep = sum(r.get("duration_min", 0) for r in sleep_data)
        deep = sum(r.get("duration_min", 0) for r in sleep_data if r.get("stage_id") == 2)
        rem = sum(r.get("duration_min", 0) for r in sleep_data if r.get("stage_id") == 3)
        print(f"  นอนหลับรวม       : {total_sleep:.0f} นาที ({total_sleep/60:.1f} ชั่วโมง)")
        print(f"    - หลับลึก      : {deep:.0f} นาที")
        print(f"    - หลับ REM     : {rem:.0f} นาที")

    # ความเครียด
    stress_data = data.get("stress", [])
    if stress_data:
        values = [r.get("value", 0) for r in stress_data if r.get("value")]
        if values:
            avg = sum(values) / len(values)
            label = "ต่ำ" if avg < 40 else "ปานกลาง" if avg < 60 else "สูง"
            print(f"  ความเครียดเฉลี่ย : {avg:.1f} ({label})")

    print()


# ---------------------------------------------------------------------------
# ส่งออก CSV
# ---------------------------------------------------------------------------

def export_to_csv(data: dict[str, list[dict]], output_dir: str = ".") -> None:
    """ส่งออกข้อมูลแต่ละประเภทเป็นไฟล์ CSV"""
    os.makedirs(output_dir, exist_ok=True)
    today = datetime.now().strftime("%Y%m%d_%H%M%S")

    for name, records in data.items():
        if not records:
            continue
        filepath = os.path.join(output_dir, f"health_{name}_{today}.csv")
        headers = list(records[0].keys())
        with open(filepath, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=headers)
            writer.writeheader()
            writer.writerows(records)
        print(f"  [✓] บันทึก {name} → {filepath} ({len(records)} รายการ)")


def export_to_json(data: dict[str, list[dict]], filepath: str = "health_data.json") -> None:
    """ส่งออกข้อมูลทั้งหมดเป็นไฟล์ JSON"""
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"\n[✓] บันทึกข้อมูลทั้งหมด → {filepath}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def parse_args() -> tuple[datetime, datetime, str, bool, bool]:
    """แยก command-line arguments อย่างง่าย"""
    import argparse

    parser = argparse.ArgumentParser(
        description="ดึงข้อมูลสุขภาพจาก HUAWEI Health Kit API",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
ตัวอย่าง:
  python huawei_health.py                          # ดึงข้อมูล 7 วันล่าสุด
  python huawei_health.py --days 30                # ดึงข้อมูล 30 วันล่าสุด
  python huawei_health.py --start 2025-01-01       # กำหนดวันเริ่มต้น
  python huawei_health.py --export csv             # ส่งออกเป็น CSV
  python huawei_health.py --export json            # ส่งออกเป็น JSON
  python huawei_health.py --export both            # ส่งออกทั้ง CSV และ JSON
        """,
    )
    parser.add_argument("--start", type=str, help="วันเริ่มต้น (YYYY-MM-DD)")
    parser.add_argument("--end", type=str, help="วันสิ้นสุด (YYYY-MM-DD)")
    parser.add_argument("--days", type=int, default=7, help="จำนวนวันย้อนหลัง (default: 7)")
    parser.add_argument(
        "--export",
        choices=["csv", "json", "both", "none"],
        default="none",
        help="รูปแบบการส่งออกข้อมูล",
    )
    parser.add_argument("--verbose", action="store_true", help="แสดงข้อมูลรายละเอียด")
    parser.add_argument("--token", type=str, help="Access Token (ถ้ามี)")

    args = parser.parse_args()

    end_time = datetime.now()
    if args.end:
        end_time = datetime.strptime(args.end, "%Y-%m-%d").replace(
            hour=23, minute=59, second=59
        )

    if args.start:
        start_time = datetime.strptime(args.start, "%Y-%m-%d")
    else:
        start_time = end_time - timedelta(days=args.days)

    return start_time, end_time, args.export, args.verbose, args.token


def main() -> None:
    start_time, end_time, export_fmt, verbose, token = parse_args()

    # สร้าง client
    client = HuaweiHealthClient()

    # ตั้งค่า token ถ้ามี
    if token:
        client.set_access_token(token)

    # ดึงข้อมูลทั้งหมด
    data = client.get_all_data(start_time, end_time)

    # สรุปผล
    summarize(data)

    # แสดงรายละเอียด (ถ้า --verbose)
    if verbose:
        print("\n" + "="*60)
        print("รายละเอียดข้อมูล")
        print("="*60)
        for name, records in data.items():
            info = DATA_TYPES.get(name, {})
            title = info.get("description", name)
            unit = info.get("unit", "")
            print_table(records, title, unit)

    # ส่งออก
    if export_fmt in ("csv", "both"):
        print("\nส่งออกไฟล์ CSV:")
        export_to_csv(data, output_dir="health_export")

    if export_fmt in ("json", "both"):
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        export_to_json(data, filepath=f"health_export/health_data_{ts}.json")


if __name__ == "__main__":
    main()
