# HUAWEI Health Kit API — Python Client

อ่านข้อมูลสุขภาพทั้งหมดจาก **HUAWEI Health Kit REST API** ด้วย Python

## ข้อมูลที่รองรับ

| ประเภท | รายละเอียด | หน่วย |
|--------|-----------|-------|
| ก้าวเดิน | Steps per day | ก้าว |
| อัตราการเต้นหัวใจ | Heart Rate | bpm |
| แคลอรี่ | Calories burned | kcal |
| ระยะทาง | Distance | เมตร / km |
| การนอนหลับ | Sleep stages (light/deep/REM) | นาที |
| SpO2 | Blood oxygen saturation | % |
| ความดันโลหิต | Blood Pressure (systolic/diastolic) | mmHg |
| น้ำหนัก | Body weight | kg |
| ความเครียด | Stress level | คะแนน 0-100 |

---

## วิธีเตรียม Credentials

### 1. สมัครบัญชี HUAWEI Developer
- ไปที่ https://developer.huawei.com/consumer/en/
- สมัครบัญชีและยืนยันตัวตน

### 2. สร้าง Project ใน AppGallery Connect
1. เปิด https://developer.huawei.com/consumer/en/service/josp/agc/index.html
2. คลิก **My Projects** → **Add Project**
3. ตั้งชื่อ project แล้วไปที่ **General information**
4. บันทึก `App ID` และ `App Secret` (= `client_id` และ `client_secret`)

### 3. เปิดใช้งาน Health Kit
1. ไปที่ **API Management** ใน AppGallery Connect
2. เปิดใช้ **Health Kit**
3. กำหนด scope ที่ต้องการ:
   - `https://www.huawei.com/healthkit/stepcounts.read`
   - `https://www.huawei.com/healthkit/heartrate.read`
   - `https://www.huawei.com/healthkit/sleep.read`
   - `https://www.huawei.com/healthkit/calories.read`
   - `https://www.huawei.com/healthkit/oxygenstaturation.read`
   - `https://www.huawei.com/healthkit/bloodpressure.read`

### 4. OAuth2 Authorization (รับ Access Token)
เนื่องจาก Health Kit ใช้ข้อมูลส่วนบุคคล ต้องขอสิทธิ์จากผู้ใช้ผ่าน Authorization Code Flow:

```
GET https://oauth-login.cloud.huawei.com/oauth2/v3/authorize
  ?response_type=code
  &client_id=YOUR_CLIENT_ID
  &redirect_uri=YOUR_REDIRECT_URI
  &scope=https://www.huawei.com/healthkit/stepcounts.read+...
```

จากนั้นแลก `code` เป็น Access Token:
```
POST https://oauth-login.cloud.huawei.com/oauth2/v3/token
Content-Type: application/x-www-form-urlencoded

grant_type=authorization_code
&client_id=YOUR_CLIENT_ID
&client_secret=YOUR_CLIENT_SECRET
&redirect_uri=YOUR_REDIRECT_URI
&code=AUTHORIZATION_CODE
```

---

## การติดตั้ง

```bash
pip install -r requirements.txt
```

## การตั้งค่า

```bash
cp .env.example .env
# แก้ไขไฟล์ .env ใส่ Client ID, Client Secret และ Access Token
```

ตัวอย่าง `.env`:
```
HUAWEI_CLIENT_ID=12345678
HUAWEI_CLIENT_SECRET=abcdefghij1234567890
HUAWEI_ACCESS_TOKEN=AT-xxxxxxxxxxxxxx
HUAWEI_API_REGION=EU
```

---

## การใช้งาน

### ดึงข้อมูล 7 วันล่าสุด (default)
```bash
python huawei_health.py
```

### ดึงข้อมูล 30 วันล่าสุด
```bash
python huawei_health.py --days 30
```

### กำหนดช่วงวันที่
```bash
python huawei_health.py --start 2025-01-01 --end 2025-01-31
```

### แสดงรายละเอียดข้อมูล
```bash
python huawei_health.py --verbose
```

### ส่งออกเป็น CSV
```bash
python huawei_health.py --export csv
```

### ส่งออกเป็น JSON
```bash
python huawei_health.py --export json
```

### ส่งออกทั้ง CSV และ JSON
```bash
python huawei_health.py --days 30 --export both --verbose
```

### ใช้ Access Token โดยตรง (ไม่ต้องใช้ .env)
```bash
python huawei_health.py --token "AT-xxxxxxxxxxxxxx"
```

---

## ใช้งานใน Python Code

```python
from datetime import datetime, timedelta
from huawei_health import HuaweiHealthClient, summarize, export_to_csv

# สร้าง client
client = HuaweiHealthClient(
    client_id="YOUR_CLIENT_ID",
    client_secret="YOUR_CLIENT_SECRET",
    region="EU",  # CN, EU, AS, RU
)

# ตั้งค่า access token (จาก OAuth2 Authorization Code Flow)
client.set_access_token("AT-xxxxxxxxxxxxxx")

# กำหนดช่วงเวลา
end = datetime.now()
start = end - timedelta(days=7)

# ดึงข้อมูลทั้งหมด
data = client.get_all_data(start, end)

# สรุปผล
summarize(data)

# ดึงเฉพาะก้าวเดิน
steps = client.get_steps(start, end)
print(steps)

# ดึงเฉพาะการนอนหลับ
sleep = client.get_sleep(start, end)
print(sleep)

# ส่งออก CSV
export_to_csv(data, output_dir="health_export")
```

---

## โครงสร้างไฟล์

```
HUAWEIHealth/
├── huawei_health.py     # Script หลัก
├── requirements.txt     # Dependencies
├── .env.example         # ตัวอย่างการตั้งค่า
├── .env                 # ไฟล์ตั้งค่าจริง (ไม่ควร commit)
└── health_export/       # โฟลเดอร์ผลลัพธ์ (สร้างอัตโนมัติ)
    ├── health_steps_YYYYMMDD.csv
    ├── health_heart_rate_YYYYMMDD.csv
    └── health_data_YYYYMMDD.json
```

---

## ข้อควรระวัง

- **Access Token** มีอายุ 60 นาที ต้องต่ออายุด้วย Refresh Token
- ข้อมูล Health เป็นข้อมูลส่วนบุคคล ต้องปฏิบัติตาม PDPA/GDPR
- บาง data type อาจไม่มีข้อมูลถ้าอุปกรณ์ไม่รองรับ
- อย่า commit ไฟล์ `.env` ขึ้น Git

## เอกสารอ้างอิง

- [HUAWEI Health Kit Documentation](https://developer.huawei.com/consumer/en/doc/HMSCore-Guides/health-overview-0000001055038982)
- [Health Kit REST API Reference](https://developer.huawei.com/consumer/en/doc/HMSCore-References/rest-api-data-query-0000001071669814)
- [OAuth 2.0 Guide](https://developer.huawei.com/consumer/en/doc/HMSCore-Guides/open-platform-oauth-0000001050048887)
