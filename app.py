# PINYIN MASTER V6.1
# Monthly calendar + Mon/Wed lessons + 02/09 holiday
# Day 1 = 19/08/2026
# Gemini Developer API only

import os
import json
import re
import uuid
import requests
import csv
import io
from dotenv import load_dotenv
from fastapi import FastAPI, UploadFile, File, Form
from fastapi.responses import HTMLResponse, Response, StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from google import genai
from google.genai import types

load_dotenv()
API_KEY = os.getenv("GEMINI_API_KEY")
if not API_KEY:
    raise ValueError("Không tìm thấy GEMINI_API_KEY trong file .env")

MODEL = "gemini-3.1-flash-lite"
VERSION = "6.5.1-product"
client = genai.Client(api_key=API_KEY)

SUPABASE_URL = (os.getenv("SUPABASE_URL") or "").rstrip("/")
SUPABASE_SERVICE_KEY = os.getenv("SUPABASE_SERVICE_KEY")

if not SUPABASE_URL:
    raise ValueError("Không tìm thấy SUPABASE_URL trong file .env")
if not SUPABASE_SERVICE_KEY:
    raise ValueError("Không tìm thấy SUPABASE_SERVICE_KEY trong file .env")

SUPABASE_HEADERS = {
    "apikey": SUPABASE_SERVICE_KEY,
    "Authorization": f"Bearer {SUPABASE_SERVICE_KEY}",
}
AUDIO_BUCKET = "student-audio"
GOOGLE_SHEET_WEBAPP_URL = (os.getenv("GOOGLE_SHEET_WEBAPP_URL") or "").strip()

if not GOOGLE_SHEET_WEBAPP_URL:
    print("WARNING: GOOGLE_SHEET_WEBAPP_URL chưa được cấu hình; app sẽ không đọc được dữ liệu bài học động.")

app = FastAPI(title="Pinyin Master", version=VERSION)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

COURSE_CONFIG = {
    "start_date": "2026-08-19",
    "study_weekdays": [0, 2],  # Monday=0, Wednesday=2
    "holidays": {
        "2026-09-02": "Nghỉ lễ Quốc khánh"
    }
}

# V6.4.1: Nội dung bài học không hard-code trong Python.
# Google Sheet "Bài học cần luyện" là nguồn dữ liệu duy nhất.
COURSE_DATA = {}


def extract_json(text):
    if not text:
        raise ValueError("Gemini không trả nội dung.")
    cleaned = str(text).strip()
    cleaned = re.sub(r"^```json\s*", "", cleaned, flags=re.I)
    cleaned = re.sub(r"^```\s*", "", cleaned)
    cleaned = re.sub(r"\s*```$", "", cleaned).strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        start, end = cleaned.find("{"), cleaned.rfind("}")
        if start >= 0 and end > start:
            return json.loads(cleaned[start:end+1])
    raise ValueError("Không đọc được JSON từ Gemini.")

def score10(value):
    try:
        return round(max(0.0, min(10.0, float(value))), 1)
    except Exception:
        return 0.0

def fetch_course_from_google_sheet():
    if not GOOGLE_SHEET_WEBAPP_URL:
        raise RuntimeError("Chưa có GOOGLE_SHEET_WEBAPP_URL trong .env")
    r = requests.get(GOOGLE_SHEET_WEBAPP_URL, params={"action":"course"}, timeout=30)
    if not r.ok:
        raise RuntimeError(f"Không đọc được Google Sheet: {r.status_code} {r.text}")
    data = r.json()
    if not data.get("success"):
        raise RuntimeError(data.get("error") or "Google Sheet không trả dữ liệu hợp lệ.")
    course = data.get("course") or {}
    if not course:
        raise RuntimeError("Google Sheet chưa có bài học active.")
    return course

def find_item(day_id, item_id, course=None):
    course = course or fetch_course_from_google_sheet()
    lesson = course.get(day_id)
    if not lesson:
        return None, None
    for item in lesson.get("items", []):
        if str(item.get("id")) == str(item_id):
            return lesson, item
    return lesson, None

def sync_submission_to_google_sheet(submission_id, student_id, student_name, lesson, item, result):
    if not GOOGLE_SHEET_WEBAPP_URL:
        return {"success": False, "error": "GOOGLE_SHEET_WEBAPP_URL chưa cấu hình"}
    payload = {
        "action": "submission",
        "attempt_id": str(submission_id),
        "student_id": student_id,
        "student_name": student_name,
        "day": lesson.get("day"),
        "lesson_item_id": item.get("id"),
        "hanzi": item.get("hanzi"),
        "target_pinyin": item.get("pinyin"),
        "recognized_hanzi": result.get("heard_hanzi") or "",
        "recognized_pinyin": result.get("heard_pinyin") or "",
        "overall_score": result.get("overall_score"),
        "initial_score": result.get("initial_score"),
        "final_score": result.get("final_score"),
        "tone_score": result.get("tone_score"),
        "needs_retry": bool((result.get("overall_score") or 0) < 7 or (result.get("tone_score") or 0) < 7),
        "ai_feedback": result.get("feedback") or "",
        "mouth_tip": result.get("encouragement") or "",
        "teacher_review": "",
        "teacher_note": ""
    }
    r = requests.post(GOOGLE_SHEET_WEBAPP_URL, json=payload, timeout=30)
    if not r.ok:
        raise RuntimeError(f"Không ghi được Google Sheet: {r.status_code} {r.text}")
    return r.json()


def evaluate_pronunciation(audio_bytes, mime_type, hanzi, pinyin, focus):
    prompt = f"""
Bạn là TRỢ LÝ PHÁT ÂM của Zhou Laoshi (cô Vi Hùng), hỗ trợ học viên người Việt luyện tiếng Trung phổ thông.
Bạn KHÔNG tự xưng là Zhou Laoshi; bạn là trợ lý của cô.

MỤC TIÊU
Hanzi: {hanzi}
Pinyin mục tiêu: {pinyin}
Trọng tâm: {focus}

CÁCH CHẤM
- Chỉ đánh giá AUDIO THỰC TẾ, không suy đoán từ chữ mục tiêu.
- Chấm âm đầu, vận mẫu, thanh điệu ĐỘC LẬP; overall ưu tiên 25% / 30% / 45%.
- THANH ĐIỆU là tiêu chí bắt buộc: phải nghe đường nét cao độ thực tế của từng âm tiết và đối chiếu với thanh mục tiêu. Không được cho đúng thanh chỉ vì nhận ra đúng từ/Hanzi.
- Nếu người học đọc đúng âm đầu và vận mẫu nhưng sai thanh, tone_score PHẢI giảm tương ứng.
- Nếu sai rõ một thanh (đọc nhầm thanh 1/2/3/4 hoặc thành khinh thanh), tone_score không được cao hơn 6.5.
- Nếu thanh chưa đủ chuẩn nhưng còn nhận ra hướng thanh, tone_score nên ở khoảng 6.5–8.0, không mặc định 9–10.
- Với biến điệu/khinh thanh, chấm theo DẠNG ĐỌC THỰC TẾ được yêu cầu trong Pinyin/trọng tâm.
- Nếu audio chưa rõ hoặc chưa chắc, phản hồi thận trọng; không tự động cho điểm cao.
- Khen ngợi chỉ là PHONG CÁCH DIỄN ĐẠT, không được làm tăng điểm hoặc che lỗi.
- Luôn ghi nhận một điều học viên làm tốt trước khi chỉ ra lỗi, NẾU thực sự có điểm làm tốt.
- Mỗi lượt chỉ chọn MỘT điểm quan trọng nhất để luyện thêm.
- Ưu tiên đúng trọng tâm của mục luyện.
- Không dùng lời phán xét nặng.
- Nếu không có lỗi đáng kể, main_issue phải là "" và problem_syllable cũng có thể là "".
- Tuyệt đối không trả "Không có", "None", "N/A" cho main_issue.
- feedback: 1–2 câu tiếng Việt tự nhiên, dễ hiểu.
- encouragement: một mẹo nhỏ hoặc lời mời đọc lại cụ thể, ngắn.

GIỌNG PHẢN HỒI
9.0–10: Rất tốt!
8.0–8.9: Khá tốt!
6.5–7.9: Thử chỉnh một chút
<6.5: Mình luyện lại nhé

Status kỹ thuật chỉ dùng: "Tốt", "Khá", "Cần luyện".

Chỉ trả JSON:
{{
  "heard_pinyin":"",
  "initial_score":0,
  "final_score":0,
  "tone_score":0,
  "overall_score":0,
  "initial_status":"",
  "final_status":"",
  "tone_status":"",
  "problem_syllable":"",
  "main_issue":"",
  "feedback":"",
  "encouragement":""
}}
Không markdown.
"""
    response = client.models.generate_content(
        model=MODEL,
        contents=[prompt, types.Part.from_bytes(data=audio_bytes, mime_type=mime_type)],
        config=types.GenerateContentConfig(temperature=0.15, response_mime_type="application/json"),
    )
    result = extract_json(response.text)
    for key in ["initial_score", "final_score", "tone_score", "overall_score"]:
        result[key] = score10(result.get(key, 0))
    issue = str(result.get("main_issue") or "").strip()
    if issue.lower() in {"không có","khong co","none","n/a","null","no issue","không"}:
        result["main_issue"] = ""
    tone = float(result.get("tone_score") or 0)
    if tone < 8:
        result["tone_status"] = "Cần luyện" if tone < 6.5 else "Khá"
        if not str(result.get("main_issue") or "").strip():
            result["main_issue"] = "Thanh điệu cần chỉnh"
        fb = str(result.get("feedback") or "").strip()
        if not any(w in fb.lower() for w in ["thanh", "cao độ", "giọng"]):
            result["feedback"] = (fb + " " if fb else "") + "Thanh điệu là điểm bạn cần ưu tiên chỉnh ở lượt này."
    return result


def safe_filename_part(value):
    value = str(value or "").strip()
    value = re.sub(r"[^A-Za-z0-9_-]+", "_", value)
    return value.strip("_")[:80] or "student"

def upload_audio_to_supabase(audio_bytes, mime_type, student_id, day_number, item_id):
    extension = "webm"
    mt = (mime_type or "").lower()
    if "wav" in mt:
        extension = "wav"
    elif "mp4" in mt or "m4a" in mt:
        extension = "m4a"
    elif "ogg" in mt:
        extension = "ogg"

    student_key = safe_filename_part(student_id)
    item_key = safe_filename_part(item_id)
    unique = uuid.uuid4().hex[:12]
    audio_path = f"day-{day_number:02d}/{student_key}/{item_key}_{unique}.{extension}"

    url = f"{SUPABASE_URL}/storage/v1/object/{AUDIO_BUCKET}/{audio_path}"
    headers = {
        **SUPABASE_HEADERS,
        "Content-Type": mime_type or "audio/webm",
        "x-upsert": "false",
    }
    response = requests.post(url, headers=headers, data=audio_bytes, timeout=30)
    if not response.ok:
        raise RuntimeError(f"Không lưu được audio vào Supabase: {response.status_code} {response.text}")
    return audio_path

def insert_submission(student_name, student_id, lesson, item, audio_path, result):
    payload = {
        "student_name": student_name or "Chưa chọn học viên",
        "student_id": student_id or None,
        "day_number": lesson["day"],
        "day_id": f"day{lesson['day']}",
        "item_id": item["id"],
        "hanzi": item["hanzi"],
        "pinyin": item["pinyin"],
        "meaning": item.get("meaning"),
        "focus": item.get("focus"),
        "audio_path": audio_path,
        "heard_pinyin": result.get("heard_pinyin"),
        "initial_score": result.get("initial_score"),
        "final_score": result.get("final_score"),
        "tone_score": result.get("tone_score"),
        "overall_score": result.get("overall_score"),
        "initial_status": result.get("initial_status"),
        "final_status": result.get("final_status"),
        "tone_status": result.get("tone_status"),
        "problem_syllable": result.get("problem_syllable"),
        "main_issue": result.get("main_issue"),
        "feedback": result.get("feedback"),
        "encouragement": result.get("encouragement"),
    }
    url = f"{SUPABASE_URL}/rest/v1/submissions"
    headers = {
        **SUPABASE_HEADERS,
        "Content-Type": "application/json",
        "Prefer": "return=representation",
    }
    response = requests.post(url, headers=headers, json=payload, timeout=30)
    if not response.ok:
        raise RuntimeError(f"Không lưu được submission: {response.status_code} {response.text}")
    rows = response.json()
    return rows[0] if rows else payload

def list_submissions(limit=300):
    limit = max(1, min(int(limit), 1000))
    url = f"{SUPABASE_URL}/rest/v1/submissions"
    params = {
        "select": "*",
        "order": "created_at.desc",
        "limit": str(limit),
    }
    response = requests.get(url, headers=SUPABASE_HEADERS, params=params, timeout=30)
    if not response.ok:
        raise RuntimeError(f"Không đọc được submissions: {response.status_code} {response.text}")
    return response.json()

def create_signed_audio_url(audio_path, expires_in=3600):
    url = f"{SUPABASE_URL}/storage/v1/object/sign/{AUDIO_BUCKET}/{audio_path}"
    headers = {**SUPABASE_HEADERS, "Content-Type": "application/json"}
    response = requests.post(url, headers=headers, json={"expiresIn": expires_in}, timeout=30)
    if not response.ok:
        raise RuntimeError(f"Không tạo được signed URL: {response.status_code} {response.text}")
    data = response.json()
    signed = data.get("signedURL") or data.get("signedUrl") or data.get("signed_url")
    if not signed:
        raise RuntimeError("Supabase không trả signed URL.")
    if signed.startswith("http"):
        return signed
    if not signed.startswith("/"):
        signed = "/" + signed
    return SUPABASE_URL + signed

@app.get("/api/course")
def get_course():
    try:
        course = fetch_course_from_google_sheet()
        return {
            "success": True,
            "version": VERSION,
            "course": course,
            "config": COURSE_CONFIG,
            "source": "google-sheet-live",
        }
    except Exception as error:
        return {"success": False, "error": str(error)}

@app.post("/api/evaluate")
async def evaluate(
    audio: UploadFile = File(...),
    day_id: str = Form(...),
    item_id: str = Form(...),
    student_name: str = Form(""),
    student_id: str = Form(""),
):
    try:
        course = fetch_course_from_google_sheet()
        lesson, item = find_item(day_id, item_id, course)
        if not lesson or not item:
            return {"success": False, "error": "Không tìm thấy bài/từ luyện."}
        audio_bytes = await audio.read()
        if len(audio_bytes) < 1000:
            return {"success": False, "error": "Bản ghi quá ngắn. Hãy thử đọc lại."}
        if len(audio_bytes) > 8 * 1024 * 1024:
            return {"success": False, "error": "Bản ghi quá dài."}

        mime_type = audio.content_type or "audio/webm"
        result = evaluate_pronunciation(
            audio_bytes,
            mime_type,
            item["hanzi"],
            item["pinyin"],
            item["focus"],
        )

        saved_name = student_name.strip() or "Chưa nhập tên"
        audio_path = upload_audio_to_supabase(
            audio_bytes,
            mime_type,
            student_id.strip(),
            lesson["day"],
            item["id"],
        )
        submission = insert_submission(
            saved_name,
            student_id.strip(),
            lesson,
            item,
            audio_path,
            result,
        )

        sheet_sync = {"success": False}
        try:
            sheet_sync = sync_submission_to_google_sheet(
                submission.get("id"),
                student_id.strip(),
                saved_name,
                lesson,
                item,
                result,
            )
        except Exception as sync_error:
            print("GOOGLE SHEET SYNC ERROR:", repr(sync_error))

        return {
            "success": True,
            "version": VERSION,
            "student_name": saved_name,
            "day_id": day_id,
            "day": lesson["day"],
            "item": item,
            "result": result,
            "saved": True,
            "submission_id": submission.get("id"),
            "sheet_synced": bool(sheet_sync.get("success")),
        }
    except Exception as error:
        print("EVALUATE ERROR:", repr(error))
        return {"success": False, "error": str(error)}


@app.get("/api/students")
def api_students():
    try:
        url=f"{SUPABASE_URL}/rest/v1/students"
        params={"select":"id,student_code,student_name","active":"eq.true","order":"student_name.asc"}
        r=requests.get(url,headers=SUPABASE_HEADERS,params=params,timeout=30)
        if not r.ok: raise RuntimeError(f"Không đọc được danh sách học viên: {r.status_code} {r.text}")
        return {"success":True,"students":r.json()}
    except Exception as error:
        return {"success":False,"error":str(error)}

@app.post("/api/admin/teacher-feedback/{submission_id}")
async def save_teacher_feedback(submission_id:int,payload:dict):
    try:
        from datetime import datetime, timezone
        status=str(payload.get("teacher_feedback_status") or "draft")
        if status not in ("draft","sent"): status="draft"
        body={"teacher_feedback":str(payload.get("teacher_feedback") or "").strip(),
              "teacher_feedback_status":status,
              "reviewed_at":datetime.now(timezone.utc).isoformat()}
        url=f"{SUPABASE_URL}/rest/v1/submissions"
        headers={**SUPABASE_HEADERS,"Content-Type":"application/json","Prefer":"return=representation"}
        r=requests.patch(url,headers=headers,params={"id":f"eq.{submission_id}"},json=body,timeout=30)
        if not r.ok: raise RuntimeError(f"Không lưu được nhận xét GV: {r.status_code} {r.text}")
        # Đồng bộ nhận xét GV sang đúng attempt_id trong Google Sheet.
        if GOOGLE_SHEET_WEBAPP_URL:
            try:
                requests.post(
                    GOOGLE_SHEET_WEBAPP_URL,
                    json={
                        "action":"teacher_feedback",
                        "attempt_id":str(submission_id),
                        "teacher_review":status,
                        "teacher_note":body["teacher_feedback"],
                    },
                    timeout=30,
                )
            except Exception as sync_error:
                print("TEACHER FEEDBACK SHEET SYNC ERROR:", repr(sync_error))
        return {"success":True}
    except Exception as error:
        return {"success":False,"error":str(error)}

@app.get("/api/admin/export.csv")
def export_admin_csv():
    try:
        rows=list_submissions(1000)
        output=io.StringIO()
        output.write("\ufeff")
        w=csv.writer(output)
        w.writerow(["Thời gian","Mã học viên","Học viên","Day","Hanzi","Pinyin","AI nghe","Điểm tổng","Âm đầu","Vận mẫu","Thanh điệu","Feedback AI","Nhận xét giáo viên","Trạng thái nhận xét"])
        for x in rows:
            w.writerow([x.get("created_at",""),x.get("student_id",""),x.get("student_name",""),x.get("day_number",""),x.get("hanzi",""),x.get("pinyin",""),x.get("heard_pinyin",""),x.get("overall_score",""),x.get("initial_score",""),x.get("final_score",""),x.get("tone_score",""),x.get("feedback",""),x.get("teacher_feedback",""),x.get("teacher_feedback_status","")])
        data=output.getvalue().encode("utf-8")
        return StreamingResponse(io.BytesIO(data),media_type="text/csv; charset=utf-8",headers={"Content-Disposition":'attachment; filename="pinyin-master-engagement.csv"'})
    except Exception as error:
        return Response(content=str(error),status_code=500,media_type="text/plain")

@app.get("/api/admin/submissions")
def admin_submissions(limit: int = 300):
    try:
        return {"success": True, "submissions": list_submissions(limit)}
    except Exception as error:
        return {"success": False, "error": str(error)}

@app.get("/api/admin/audio-stream/{submission_id}")
def admin_audio_stream(submission_id: int):
    try:
        url = f"{SUPABASE_URL}/rest/v1/submissions"
        params = {
            "select": "id,audio_path",
            "id": f"eq.{submission_id}",
            "limit": "1",
        }
        response = requests.get(url, headers=SUPABASE_HEADERS, params=params, timeout=30)
        if not response.ok:
            raise RuntimeError(f"Không đọc được submission: {response.status_code} {response.text}")

        rows = response.json()
        if not rows:
            return Response(content="Không tìm thấy bài nộp.", status_code=404, media_type="text/plain")

        audio_path = rows[0].get("audio_path")
        if not audio_path:
            return Response(content="Bài nộp không có audio_path.", status_code=404, media_type="text/plain")

        storage_url = f"{SUPABASE_URL}/storage/v1/object/{AUDIO_BUCKET}/{audio_path}"
        audio_response = requests.get(storage_url, headers=SUPABASE_HEADERS, timeout=30)
        if not audio_response.ok:
            raise RuntimeError(
                f"Không tải được audio từ Supabase: {audio_response.status_code} {audio_response.text}"
            )

        audio_bytes = audio_response.content
        if not audio_bytes:
            return Response(content="File audio rỗng.", status_code=404, media_type="text/plain")

        content_type = (audio_response.headers.get("content-type") or "").split(";")[0].strip()
        lower_path = audio_path.lower()
        if not content_type.startswith("audio/") and not content_type.startswith("video/"):
            if lower_path.endswith(".webm"):
                content_type = "audio/webm"
            elif lower_path.endswith(".wav"):
                content_type = "audio/wav"
            elif lower_path.endswith(".ogg"):
                content_type = "audio/ogg"
            elif lower_path.endswith(".m4a") or lower_path.endswith(".mp4"):
                content_type = "audio/mp4"
            else:
                content_type = "application/octet-stream"

        return Response(
            content=audio_bytes,
            media_type=content_type,
            headers={
                "Content-Length": str(len(audio_bytes)),
                "Cache-Control": "private, max-age=300",
                "Content-Disposition": 'inline; filename="student-audio"',
            },
        )

    except Exception as error:
        print("ADMIN AUDIO STREAM ERROR:", repr(error))
        return Response(
            content=f"Lỗi phát audio: {error}",
            status_code=500,
            media_type="text/plain",
        )

@app.get("/admin", response_class=HTMLResponse)
def admin_page():
    return HTMLResponse(r"""
<!DOCTYPE html>
<html lang="vi">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Pinyin Master · Teacher Admin</title>
<style>
*{box-sizing:border-box}body{margin:0;background:#f5f7f5;color:#20342d;font-family:Arial,"Microsoft YaHei",sans-serif}
.wrap{max-width:1180px;margin:auto;padding:28px 16px 60px}.top{display:flex;justify-content:space-between;align-items:flex-end;gap:15px;margin-bottom:18px}
.eyebrow{font-size:11px;letter-spacing:1.5px;color:#7d8c85}.title{font-size:28px;font-weight:800;color:#194839}.sub{color:#7d8c85;margin-top:5px;font-size:13px}
.card{background:white;border-radius:20px;padding:18px;box-shadow:0 8px 35px rgba(31,58,47,.055)}
.filters{display:grid;grid-template-columns:2fr 1fr 1fr auto auto;gap:9px;margin-bottom:15px}
input,select,button{min-height:42px;border-radius:11px;border:1px solid #e1e9e5;padding:0 12px;font:inherit;background:#fff}
button{cursor:pointer;font-weight:700;color:#285f4d}.refresh{background:#285f4d;color:white;border-color:#285f4d}
.summary{display:flex;gap:9px;flex-wrap:wrap;margin-bottom:14px}.pill{background:#eaf3ef;color:#285f4d;border-radius:20px;padding:7px 11px;font-size:12px;font-weight:700}
.tablewrap{overflow:auto}table{width:100%;border-collapse:collapse;min-width:940px}th{text-align:left;font-size:10px;letter-spacing:.6px;color:#7d8c85;padding:10px;border-bottom:1px solid #e1e9e5}
td{padding:11px 10px;border-bottom:1px solid #edf1ef;font-size:13px;vertical-align:top}.hanzi{font-size:21px;font-weight:700}.py{color:#285f4d;font-weight:700}
.score{font-size:18px;font-weight:800}.low{color:#a94848}.good{color:#285f4d}.listen{border:0;background:#eaf3ef;color:#285f4d;min-height:34px;padding:0 11px}
.detail{max-width:300px;color:#596760;line-height:1.4}.muted{color:#8b9891}.empty{text-align:center;padding:35px;color:#7d8c85}
audio{width:240px;height:34px}.date{white-space:nowrap;font-size:11px;color:#7d8c85}
@media(max-width:700px){.top{align-items:flex-start;flex-direction:column}.filters{grid-template-columns:1fr 1fr}.filters input{grid-column:1/-1}.wrap{padding:18px 10px}}
</style>
</head>
<body><div class="wrap">
<div class="top"><div><div class="eyebrow">LÀM CHỦ PHÁT ÂM, TỰ TIN GIAO TIẾP · PINYIN MASTER</div><div class="title">Teacher Admin</div><div class="sub">Nghe lại bài học viên · kiểm tra điểm Gemini · lọc các trường hợp cần xem</div></div></div>
<div class="card">
<div class="filters">
<input id="q" placeholder="Tìm tên học viên / chữ / pinyin..." oninput="render()">
<select id="day" onchange="render()"><option value="">Tất cả Day</option></select>
<select id="scoreFilter" onchange="render()"><option value="">Tất cả điểm</option><option value="low">Điểm tổng < 7</option><option value="tone">Thanh điệu < 7</option></select>
<button class="refresh" onclick="loadData()">↻ Làm mới</button><button onclick="window.location.href='/api/admin/export.csv'">↓ Xuất Google Sheet</button>
</div>
<div class="summary" id="summary"></div>
<div class="tablewrap"><table><thead><tr><th>THỜI GIAN</th><th>HỌC VIÊN</th><th>DAY</th><th>TỪ</th><th>AI NGHE</th><th>ĐIỂM</th><th>AUDIO</th><th>FEEDBACK AI</th><th>GV NHẬN XÉT</th></tr></thead><tbody id="rows"></tbody></table></div>
</div></div>
<script>
let DATA=[];
function esc(s){
 const div=document.createElement("div");
 div.textContent=String(s??"");
 return div.innerHTML;
}
function fmtDate(v){if(!v)return "";let d=new Date(v);return d.toLocaleString("vi-VN")}
async function loadData(){
 document.getElementById("rows").innerHTML='<tr><td colspan="9" class="empty">Đang tải...</td></tr>';
 try{let r=await fetch("/api/admin/submissions?limit=500"),d=await r.json();if(!d.success)throw Error(d.error);DATA=d.submissions||[];fillDays();render()}
 catch(e){document.getElementById("rows").innerHTML=`<tr><td colspan="9" class="empty">Lỗi: ${esc(e.message)}</td></tr>`}
}
function fillDays(){let s=document.getElementById("day"),cur=s.value,days=[...new Set(DATA.map(x=>x.day_number))].sort((a,b)=>a-b);s.innerHTML='<option value="">Tất cả Day</option>'+days.map(x=>`<option value="${x}">Day ${x}</option>`).join("");s.value=cur}
function filtered(){
 let q=document.getElementById("q").value.trim().toLowerCase(),day=document.getElementById("day").value,sf=document.getElementById("scoreFilter").value;
 return DATA.filter(x=>{
   if(q && !`${x.student_name} ${x.hanzi} ${x.pinyin} ${x.heard_pinyin||""}`.toLowerCase().includes(q))return false;
   if(day && String(x.day_number)!==day)return false;
   if(sf==="low" && Number(x.overall_score)>=7)return false;
   if(sf==="tone" && Number(x.tone_score)>=7)return false;
   return true;
 });
}
function render(){
 let d=filtered(),students=new Set(d.map(x=>x.student_name)).size,low=d.filter(x=>Number(x.overall_score)<7).length;
 document.getElementById("summary").innerHTML=`<span class="pill">${d.length} lượt đọc</span><span class="pill">${students} học viên</span><span class="pill">${low} lượt dưới 7</span>`;
 document.getElementById("rows").innerHTML=d.length?d.map(x=>{
   let score=Number(x.overall_score||0),cls=score<7?"low":"good";
   return `<tr><td class="date">${esc(fmtDate(x.created_at))}</td><td><strong>${esc(x.student_name)}</strong></td><td>Day ${esc(x.day_number)}</td>
   <td><div class="hanzi">${esc(x.hanzi)}</div><div class="py">${esc(x.pinyin)}</div></td><td>${esc(x.heard_pinyin||"—")}</td>
   <td><div class="score ${cls}">${esc(x.overall_score)}/10</div><div class="muted">Âm đầu ${esc(x.initial_score)} · Vận ${esc(x.final_score)} · Thanh ${esc(x.tone_score)}</div></td>
   <td id="audio-${x.id}"><button class="listen" onclick="playAudio(${x.id})">▶ Nghe</button></td>
   <td class="detail"><strong>${esc(x.main_issue||"")}</strong><br>${esc(x.feedback||"")}</td>
   <td class="detail"><textarea id="tf-${x.id}" style="width:250px;min-height:72px;border:1px solid #e1e9e5;border-radius:10px;padding:8px">${esc(x.teacher_feedback||"")}</textarea>
   <div style="display:flex;gap:6px;margin-top:6px"><button onclick="saveFeedback(${x.id},'draft')">Lưu nháp</button><button class="refresh" onclick="saveFeedback(${x.id},'sent')">Gửi học viên</button></div>
   <div class="muted" id="tfs-${x.id}">${x.teacher_feedback_status==="sent"?"✓ Đã gửi":"Nháp"}</div></td></tr>`}).join("")
   :'<tr><td colspan="9" class="empty">Chưa có dữ liệu phù hợp.</td></tr>';
}
function playAudio(id){
 let box=document.getElementById("audio-"+id);
 let src="/api/admin/audio-stream/"+id+"?t="+Date.now();
 box.innerHTML=`<audio controls autoplay preload="metadata" src="${src}"></audio>`;
 let player=box.querySelector("audio");
 player.addEventListener("error",()=>{
   box.innerHTML='<span class="low">Không phát được audio. Kiểm tra log Python.</span>';
 });
}
async function saveFeedback(id,status){
 const text=document.getElementById("tf-"+id).value,label=document.getElementById("tfs-"+id);label.textContent="Đang lưu...";
 try{const r=await fetch("/api/admin/teacher-feedback/"+id,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({teacher_feedback:text,teacher_feedback_status:status})});
 const d=await r.json();if(!d.success)throw Error(d.error);label.textContent=status==="sent"?"✓ Đã gửi học viên":"Đã lưu nháp";
 const row=DATA.find(x=>x.id===id);if(row){row.teacher_feedback=text;row.teacher_feedback_status=status}}
 catch(e){label.textContent="Lỗi: "+e.message}
}

loadData();
</script></body></html>
""")

@app.get("/health")
def health():
    return {
        "success": True,
        "version": VERSION,
        "provider": "Gemini Developer API",
        "model": MODEL,
        "vertex": False,
    }

@app.get("/", response_class=HTMLResponse)
def home():
    return HTMLResponse(r"""
<!DOCTYPE html>
<html lang="vi">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>Luyện âm cùng trợ lý Zhou Laoshi</title>
<style>
*{box-sizing:border-box}
:root{--g:#285f4d;--gd:#194839;--gs:#eaf3ef;--light:#f4f8f6;--tx:#20342d;--mu:#7d8c85;--bd:#e1e9e5;--cream:#fff9ec;--red:#a94848}
body{margin:0;background:#f5f7f5;color:var(--tx);font-family:Arial,"Microsoft YaHei","Noto Sans",sans-serif}
button,input{font-family:inherit}.app{max-width:820px;margin:auto;padding:24px 16px 70px}
.header{display:flex;justify-content:space-between;align-items:center;gap:15px;margin-bottom:18px}
.logo-small{font-size:11px;letter-spacing:1.5px;color:var(--mu);margin-bottom:4px}.logo{font-size:26px;font-weight:800;color:var(--gd)}
.student select{min-width:220px;padding:11px 13px;border:1px solid var(--bd);border-radius:12px;outline:none;background:#fff}
.card{background:#fff;border-radius:24px;padding:20px;box-shadow:0 8px 35px rgba(31,58,47,.055);margin-bottom:16px}
.cal-top{display:flex;align-items:center;justify-content:space-between;margin-bottom:14px}.month{font-size:18px;font-weight:800}
.month-btn{width:38px;height:38px;border:0;border-radius:50%;background:var(--gs);color:var(--g);font-size:22px;cursor:pointer}
.week,.calendar{display:grid;grid-template-columns:repeat(7,1fr);gap:6px}.week div{text-align:center;color:var(--mu);font-size:11px;font-weight:700;padding:5px}
.cell{position:relative;min-height:82px;border:1px solid var(--bd);border-radius:13px;padding:8px;background:#fff}
.cell.empty{border-color:transparent;background:transparent}.date-num{font-weight:800}.cell.today{outline:2px solid var(--g)}
.cell.lesson{background:#f7faf8;cursor:pointer}.cell.lesson:hover{border-color:#9dbdaf}.cell.locked{background:#fafafa;color:#939e98;cursor:not-allowed}
.cell.done{background:var(--gs)}.cell.holiday{background:#fff7ed}.lock{position:absolute;top:7px;right:7px;font-size:12px}
.day-badge{margin-top:9px;color:var(--g);font-size:10px;font-weight:800}.holiday .day-badge{color:#a65b30}.today-dot{color:var(--g);font-size:9px}
.no-data{margin-top:9px;color:#a6b0ab;font-size:9px;line-height:1.3}
.lesson-day{font-size:11px;font-weight:800;letter-spacing:1.2px;color:var(--g)}.lesson-title{font-size:25px;font-weight:800;margin:7px 0 3px}
.lesson-subtitle{color:var(--g);font-weight:700}.lesson-description{margin-top:8px;color:var(--mu);font-size:13px;line-height:1.5}
.item-nav{display:flex;flex-wrap:wrap;gap:7px;margin-top:19px}.item-dot{width:34px;height:34px;border:1px solid var(--bd);border-radius:50%;background:#fff;color:var(--mu);cursor:pointer}
.item-dot.selected{background:var(--g);color:#fff;border-color:var(--g)}.item-dot.done:not(.selected){background:var(--gs);color:var(--g)}
.practice{text-align:center;padding:29px 0 5px}.focus{display:inline-block;padding:6px 11px;border-radius:20px;background:var(--gs);color:var(--g);font-size:11px;font-weight:700}
.hanzi{margin-top:15px;font-size:72px;line-height:1.1;font-weight:700}.pinyin{margin-top:9px;font-size:29px;font-weight:700;color:var(--g)}
.meaning{margin-top:6px;color:var(--mu);font-size:14px}.actions{display:grid;grid-template-columns:1fr 1.35fr;gap:10px;margin-top:25px}
.action{min-height:55px;border:0;border-radius:15px;font-size:15px;font-weight:700;cursor:pointer}.listen{background:var(--gs);color:var(--g)}.record{background:var(--g);color:#fff}
.record.recording{background:var(--red)}.action:disabled{opacity:.5}.status{min-height:22px;margin-top:14px;text-align:center;color:var(--mu);font-size:13px}
.result{display:none;margin-top:25px;padding-top:23px;border-top:1px solid var(--bd)}.result-title{text-align:center;color:var(--mu);font-size:11px;font-weight:700;letter-spacing:1px}
.overall{text-align:center;margin-top:8px}.overall-number{font-size:65px;line-height:1;font-weight:800;color:var(--gd)}.overall-max{color:var(--mu);font-size:19px}
.heard{text-align:center;color:var(--mu);font-size:12px;margin-top:16px}.heard strong{display:block;margin-top:4px;color:var(--tx);font-size:19px}
.scores{display:grid;grid-template-columns:repeat(3,1fr);gap:8px;margin-top:18px}.score-box{padding:15px 5px;border-radius:15px;background:var(--light);text-align:center}
.score-value{font-size:24px;font-weight:800;color:var(--gd)}.score-name{margin-top:5px;color:var(--mu);font-size:10px}.score-status{margin-top:4px;color:var(--g);font-size:10px;font-weight:700}
.feedback{margin-top:12px;padding:17px;border-radius:16px;background:var(--cream);line-height:1.55;font-size:14px}.issue{font-weight:800;margin-bottom:6px}.enc{margin-top:9px;color:var(--g);font-weight:700}
.next-row{text-align:center;margin-top:15px}.next{min-height:46px;padding:0 22px;border:1px solid var(--g);border-radius:13px;background:#fff;color:var(--g);font-weight:700;cursor:pointer}
.placeholder{text-align:center;padding:35px 10px;color:var(--mu);line-height:1.6}.foot{text-align:center;margin-top:18px;color:#9aa69f;font-size:11px;line-height:1.5}
@media(max-width:600px){
.app{padding:12px 8px 34px}.header{align-items:flex-start;flex-direction:column;gap:12px}.student,.student select{width:100%}
.card{padding:13px;border-radius:18px;margin-bottom:10px}.cal-top{margin-bottom:8px}.week,.calendar{gap:3px}
.cell{min-height:58px;padding:5px;border-radius:10px}.date-num{font-size:11px}.day-badge{font-size:8px;margin-top:7px}.lock{top:5px;right:5px;font-size:10px}
.logo{font-size:23px;line-height:1.18}.brand-sub{font-size:11px;line-height:1.4}.lesson-title{font-size:22px}.lesson-subtitle{font-size:13px}.item-nav{margin-top:14px;gap:6px}.item-dot{width:32px;height:32px}
.practice{padding:22px 0 2px}.hanzi{font-size:58px}.pinyin{font-size:25px}.actions{grid-template-columns:1fr;gap:8px;margin-top:19px}
.action{min-height:58px;font-size:15px}.record{font-size:16px}.scores{grid-template-columns:repeat(3,1fr);gap:6px}.score-box{padding:11px 5px}
.feedback{padding:14px}.next{width:100%;min-height:54px;font-size:16px}.foot{margin-top:10px}
}
.complete-panel{margin-top:16px;padding:22px 16px;border-radius:18px;background:var(--gs);text-align:center}
.complete-icon{font-size:34px}.complete-title{margin-top:7px;font-size:20px;font-weight:800;color:var(--gd)}
.complete-text{margin-top:5px;color:var(--mu);font-size:13px;line-height:1.5}
.complete-btn{width:100%;min-height:54px;margin-top:15px;border:0;border-radius:14px;background:var(--g);color:#fff;font-size:16px;font-weight:800;cursor:pointer}
</style>
</head>
<body>
<div class="app">
<header class="header">
<div><div class="logo-small">ZHOU LAOSHI · CÔ VI HÙNG</div><div class="logo">Luyện âm cùng trợ lý Zhou Laoshi</div><div class="brand-sub">Mỗi ngày một chút · Trợ lý nghe và cùng bạn sửa âm</div></div>
<div class="student"><select id="studentSelect"><option value="">Chọn học viên</option></select></div>
</header>

<section class="card">
<div class="cal-top">
<button class="month-btn" onclick="moveMonth(-1)">‹</button>
<div class="month" id="monthTitle"></div>
<button class="month-btn" onclick="moveMonth(1)">›</button>
</div>
<div class="week"><div>T2</div><div>T3</div><div>T4</div><div>T5</div><div>T6</div><div>T7</div><div>CN</div></div>
<div class="calendar" id="calendar"></div>
</section>

<section class="card" id="lessonCard">
<div class="placeholder">Chọn một buổi học đã mở trên lịch để bắt đầu luyện.</div>
</section>

<div class="foot">Nghe · Đọc · Nhận phản hồi · Luyện lại<br>Vững vàng Pinyin, tự tin giao tiếp.</div>
</div>

<script>
let COURSE={}, CONFIG={}, currentDayId=null, currentItemIndex=0;
let recorder=null, audioChunks=[], mediaStream=null, sending=false;
const PROGRESS_KEY="pinyin_master_v61_progress", STUDENT_KEY="pinyin_master_v61_student";
const studentSelect=document.getElementById("studentSelect");
let STUDENTS=[];
studentSelect.addEventListener("change",()=>localStorage.setItem(STUDENT_KEY,studentSelect.value));
function escMain(s){const d=document.createElement("div");d.textContent=String(s??"");return d.innerHTML}
async function loadStudents(){
 const r=await fetch("/api/students"),d=await r.json();
 if(!d.success)throw new Error(d.error||"Không tải được danh sách học viên.");
 STUDENTS=d.students||[];
 studentSelect.innerHTML='<option value="">Chọn học viên</option>'+STUDENTS.map(s=>`<option value="${s.id}">${escMain(s.student_name)}</option>`).join("");
 const saved=localStorage.getItem(STUDENT_KEY)||"";
 if(STUDENTS.some(s=>String(s.id)===saved))studentSelect.value=saved;
}

let viewDate=new Date();
viewDate.setDate(1);

function dateString(d){
  const y=d.getFullYear(),m=String(d.getMonth()+1).padStart(2,"0"),day=String(d.getDate()).padStart(2,"0");
  return `${y}-${m}-${day}`;
}
function todayString(){return dateString(new Date())}
function getProgress(){try{return JSON.parse(localStorage.getItem(PROGRESS_KEY)||"{}")}catch{return {}}}
function saveProgress(p){localStorage.setItem(PROGRESS_KEY,JSON.stringify(p))}
function isDayComplete(id){
  const l=COURSE[id],p=getProgress();
  return !!l && l.items.every(x=>p[id]?.items?.[x.id]?.done);
}
function markItemDone(dayId,itemId,score){
  const p=getProgress(); if(!p[dayId])p[dayId]={items:{}};
  p[dayId].items[itemId]={done:true,score,updatedAt:new Date().toISOString()};
  saveProgress(p); renderCalendar(); renderItemNav();
}

/* Build fixed Mon/Wed schedule from 19/08/2026.
   02/09 is holiday and DOES NOT consume a Day number. */
function buildSchedule(maxDay=80){
  const map={};
  let d=new Date(CONFIG.start_date+"T00:00:00"), n=1, guard=0;
  while(n<=maxDay && guard<1200){
    const ds=dateString(d);
    const mondayBased=(d.getDay()+6)%7; // Mon=0 ... Sun=6
    if(CONFIG.holidays?.[ds]){
      map[ds]={holiday:true,label:CONFIG.holidays[ds]};
    }else if(CONFIG.study_weekdays.includes(mondayBased)){
      map[ds]={day:n,dayId:"day"+n}; n++;
    }
    d.setDate(d.getDate()+1); guard++;
  }
  return map;
}

function renderCalendar(){
  const cal=document.getElementById("calendar"); cal.innerHTML="";
  const y=viewDate.getFullYear(),m=viewDate.getMonth();
  document.getElementById("monthTitle").innerText=`THÁNG ${m+1} · ${y}`;
  const first=new Date(y,m,1),last=new Date(y,m+1,0);
  const offset=(first.getDay()+6)%7;
  const schedule=buildSchedule(Math.max(80,Object.keys(COURSE).length+30));

  for(let i=0;i<offset;i++){
    const blank=document.createElement("div");blank.className="cell empty";cal.appendChild(blank);
  }

  for(let day=1;day<=last.getDate();day++){
    const d=new Date(y,m,day),ds=dateString(d),info=schedule[ds];
    const cell=document.createElement("div");cell.className="cell";
    let html=`<span class="date-num">${day}</span>`;
    if(ds===todayString()){cell.classList.add("today");html+=` <span class="today-dot">●</span>`}

    if(info?.holiday){
      cell.classList.add("holiday");
      html+=`<div class="day-badge">🇻🇳 NGHỈ LỄ</div>`;
    }else if(info?.day){
      const hasData=!!COURSE[info.dayId];
      const future=ds>todayString();
      const complete=hasData&&isDayComplete(info.dayId);

      if(hasData){
        cell.classList.add("lesson");
        if(future){cell.classList.add("locked");html+=`<span class="lock">🔒</span>`}
        if(complete)cell.classList.add("done");
        html+=`<div class="day-badge">${complete?"✓ ":""}DAY ${info.day}</div>`;
        if(!future)cell.onclick=()=>openDay(info.dayId);
      }else{
        cell.classList.add("locked");
        html+=`<span class="lock">🔒</span>`;
        html+=`<div class="day-badge">DAY ${info.day}</div>`;
      }
    }
    cell.innerHTML=html;cal.appendChild(cell);
  }
}

function moveMonth(delta){viewDate.setMonth(viewDate.getMonth()+delta);renderCalendar()}

function openDay(dayId){
  if(!COURSE[dayId])return;
  currentDayId=dayId;currentItemIndex=0;
  renderCalendar();renderLesson();
  setTimeout(listenSample,300);
}

function renderLesson(){
  const l=COURSE[currentDayId];
  document.getElementById("lessonCard").innerHTML=`
    <div class="lesson-day">DAY ${l.day}</div>
    <div class="lesson-title">${l.title}</div>
    <div class="lesson-subtitle">${l.subtitle||""}</div>
    <div class="item-nav" id="itemNav"></div>
    <div class="practice">
      <div class="focus" id="focus"></div>
      <div class="hanzi" id="hanzi"></div>
      <div class="pinyin" id="pinyin"></div>
      <div class="meaning" id="meaning"></div>
    </div>
    <div class="actions">
      <button class="action listen" onclick="listenSample()">🔊 Nghe mẫu</button>
      <button class="action record" id="recordButton" onclick="toggleRecording()">🎙️ Bắt đầu đọc</button>
    </div>
    <div class="status" id="status">Nghe mẫu rồi thử đọc</div>
    <div class="result" id="result">
      <div class="result-title">TRỢ LÝ CỦA ZHOU LAOSHI</div>
      <div class="overall"><span class="overall-number" id="overallScore">--</span><span class="overall-max">/10</span></div>
      <div class="heard">TRỢ LÝ NGHE BẠN ĐỌC<strong id="heardPinyin">—</strong></div>
      <div class="scores">
        <div class="score-box"><div class="score-value" id="initialScore">--</div><div class="score-name">ÂM ĐẦU</div><div class="score-status" id="initialStatus"></div></div>
        <div class="score-box"><div class="score-value" id="finalScore">--</div><div class="score-name">VẬN MẪU</div><div class="score-status" id="finalStatus"></div></div>
        <div class="score-box"><div class="score-value" id="toneScore">--</div><div class="score-name">THANH ĐIỆU</div><div class="score-status" id="toneStatus"></div></div>
      </div>
      <div class="feedback"><div class="issue" id="mainIssue"></div><div id="feedbackText"></div><div class="enc" id="encouragement"></div></div>
      <div class="next-row"><button class="next" id="nextButton" onclick="nextItem()">Tiếp tục →</button></div>
    </div>`;
  renderItemNav();renderCurrentItem();
}

function currentItem(){return COURSE[currentDayId].items[currentItemIndex]}

function renderItemNav(){
  const nav=document.getElementById("itemNav");if(!nav)return;
  nav.innerHTML="";const p=getProgress();
  COURSE[currentDayId].items.forEach((x,i)=>{
    const b=document.createElement("button");b.className="item-dot";
    if(i===currentItemIndex)b.classList.add("selected");
    if(p[currentDayId]?.items?.[x.id]?.done)b.classList.add("done");
    b.innerText=i+1;
    b.onclick=()=>{currentItemIndex=i;renderItemNav();renderCurrentItem();setTimeout(listenSample,220)};
    nav.appendChild(b);
  });
}

function renderCurrentItem(){
  const x=currentItem();
  document.getElementById("focus").innerText=x.focus;
  document.getElementById("hanzi").innerText=x.hanzi;
  document.getElementById("pinyin").innerText=x.pinyin;
  document.getElementById("meaning").innerText=x.meaning;
  document.getElementById("result").style.display="none";
  const nextBtn=document.getElementById("nextButton");
  if(nextBtn){
    const last=currentItemIndex===COURSE[currentDayId].items.length-1;
    nextBtn.innerText=last?"✓ Hoàn thành Day":"Tiếp tục →";
  }
  const rb=document.getElementById("recordButton");
  if(x.scorable===false){
    rb.disabled=true;
    document.getElementById("status").innerText="🔒 Nội dung luyện này chưa mở.";
  }else{
    rb.disabled=false;
    document.getElementById("status").innerText="Nghe mẫu rồi thử đọc";
  }
}

function listenSample(){
  const x=currentItem();if(!x)return;
  speechSynthesis.cancel();
  const u=new SpeechSynthesisUtterance(x.hanzi);u.lang="zh-CN";u.rate=.78;
  const v=speechSynthesis.getVoices().find(v=>v.lang?.toLowerCase().startsWith("zh"));
  if(v)u.voice=v;speechSynthesis.speak(u);
}

async function toggleRecording(){
  const b=document.getElementById("recordButton");
  const status=document.getElementById("status");
  if(sending)return;

  if(recorder && recorder.state==="recording"){
    status.innerText="Đang hoàn tất bản ghi...";
    b.disabled=true;
    recorder.stop();
    return;
  }

  if(!studentSelect.value){
    status.innerText="Vui lòng chọn tên học viên trước khi ghi âm.";
    return;
  }

  try{
    if(!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia){
      throw new Error("Trình duyệt chưa cấp quyền sử dụng micro.");
    }

    mediaStream=await navigator.mediaDevices.getUserMedia({audio:true});
    audioChunks=[];

    let options={};
    if(window.MediaRecorder && MediaRecorder.isTypeSupported("audio/webm;codecs=opus")){
      options={mimeType:"audio/webm;codecs=opus"};
    }

    recorder=new MediaRecorder(mediaStream,options);

    recorder.ondataavailable=function(e){
      if(e.data && e.data.size>0)audioChunks.push(e.data);
    };

    recorder.onstop=async function(){
      const currentRecorder=recorder;
      mediaStream?.getTracks().forEach(track=>track.stop());
      mediaStream=null;

      const mime=(currentRecorder && currentRecorder.mimeType) || "audio/webm";
      const blob=new Blob(audioChunks,{type:mime});
      recorder=null;

      b.innerText="🎙️ Bắt đầu đọc";
      b.classList.remove("recording");
      b.disabled=false;

      if(blob.size===0){
        status.innerText="Không thu được âm thanh. Hãy kiểm tra quyền micro rồi thử lại.";
        return;
      }

      status.innerText="AI đang nghe và phản hồi...";
      await sendAudio(blob,mime);
    };

    recorder.onerror=function(e){
      status.innerText="Lỗi ghi âm: "+(e.error?.message||"Không xác định");
      mediaStream?.getTracks().forEach(track=>track.stop());
      mediaStream=null;
      recorder=null;
      b.innerText="🎙️ Bắt đầu đọc";
      b.classList.remove("recording");
      b.disabled=false;
    };

    recorder.start();
    b.innerText="⏹ Dừng & chấm";
    b.classList.add("recording");
    status.innerText="🎙️ Đang ghi âm — hãy đọc ngay bây giờ";
    document.getElementById("result").style.display="none";

  }catch(e){
    mediaStream?.getTracks().forEach(track=>track.stop());
    mediaStream=null;
    recorder=null;
    b.innerText="🎙️ Bắt đầu đọc";
    b.classList.remove("recording");
    b.disabled=false;

    if(e.name==="NotAllowedError"){
      status.innerText="Micro đang bị chặn. Bấm biểu tượng ổ khóa cạnh địa chỉ web → Microphone → Allow.";
    }else if(e.name==="NotFoundError"){
      status.innerText="Không tìm thấy micro trên thiết bị.";
    }else{
      status.innerText="Không mở được micro: "+e.message;
    }
  }
}
async function sendAudio(blob,mimeType="audio/webm"){
  const b=document.getElementById("recordButton"),status=document.getElementById("status"),x=currentItem();
  if(!blob || blob.size===0){status.innerText="Bản ghi chưa có âm thanh. Hãy thử lại.";b.disabled=false;return;}
  sending=true;b.disabled=true;status.innerText="AI đang nghe và phản hồi...";
  const f=new FormData();
  if(!studentSelect.value){status.innerText="Vui lòng chọn học viên trước khi nộp.";sending=false;b.disabled=false;return;}
  const st=STUDENTS.find(s=>String(s.id)===String(studentSelect.value));
  const ext=mimeType.includes("ogg")?"ogg":"webm";
  f.append("audio",blob,"recording."+ext);
  f.append("day_id",currentDayId);f.append("item_id",x.id);
  f.append("student_id",studentSelect.value);f.append("student_name",st?st.student_name:"");
  try{
    const r=await fetch("/api/evaluate",{method:"POST",body:f}),d=await r.json();
    if(!d.success)throw new Error(d.error||"Không chấm được.");
    showResult(d.result);markItemDone(currentDayId,x.id,d.result.overall_score);status.innerText="Đã nhận phản hồi";
  }catch(e){status.innerText="Lỗi: "+e.message}
  finally{
    sending=false;b.disabled=false;
    b.innerText="🎙️ Bắt đầu đọc";b.classList.remove("recording");
  }
}

function showResult(r){
  const score=Number(r.overall_score||0);
  const tone=Number(r.tone_score||0);
  let level=score>=9?"Rất tốt!":score>=8?"Khá tốt!":score>=6.5?"Thử chỉnh một chút":"Mình luyện lại nhé";
  if(tone<6.5) level="Mình luyện lại thanh điệu nhé";
  else if(tone<8 && score>=8) level="Thử chỉnh thanh điệu một chút";
  const rawIssue=String(r.main_issue||"").trim();
  const noIssue=["","không có","khong co","none","n/a","null","no issue","không"].includes(rawIssue.toLowerCase());

  document.getElementById("result").style.display="block";
  document.getElementById("overallScore").innerText=r.overall_score;
  document.getElementById("heardPinyin").innerText=r.heard_pinyin||"—";
  document.getElementById("initialScore").innerText=r.initial_score;
  document.getElementById("finalScore").innerText=r.final_score;
  document.getElementById("toneScore").innerText=r.tone_score;
  document.getElementById("initialStatus").innerText=r.initial_status||"";
  document.getElementById("finalStatus").innerText=r.final_status||"";
  document.getElementById("toneStatus").innerText=r.tone_status||"";

  const issueBox=document.getElementById("mainIssue");
  if(noIssue){
    issueBox.innerText=level;
  }else{
    issueBox.innerText=level+" · "+rawIssue;
  }

  document.getElementById("feedbackText").innerText="Trợ lý của Zhou Laoshi nhắn bạn: "+(r.feedback||"Phần này bạn đọc khá ổn rồi.");
  document.getElementById("encouragement").innerText=r.encouragement||"Giữ cách đọc này và thử thêm một lần nữa nhé!";
}
function nextItem(){
  const l=COURSE[currentDayId];
  if(currentItemIndex<l.items.length-1){
    currentItemIndex++;
    renderItemNav();
    renderCurrentItem();
    setTimeout(listenSample,250);
  }else{
    const card=document.getElementById("lessonCard");
    card.innerHTML=`
      <div class="complete-panel">
        <div class="complete-icon">✓</div>
        <div class="complete-title">Hoàn thành Day ${l.day}</div>
        <div class="complete-text">Bạn đã hoàn thành toàn bộ nội dung luyện của buổi này.</div>
        <button class="complete-btn" onclick="finishDay()">Về lịch học</button>
      </div>`;
    window.scrollTo({top:0,behavior:"smooth"});
  }
}

function finishDay(){
  currentDayId=null;
  currentItemIndex=0;
  renderCalendar();
  document.getElementById("lessonCard").innerHTML='<div class="placeholder">Chọn một buổi học đã mở trên lịch để bắt đầu luyện.</div>';
  document.querySelector(".calendar")?.scrollIntoView({behavior:"smooth",block:"start"});
}

async function init(){
  const d=await(await fetch("/api/course")).json();
  if(!d.success)throw new Error("Không tải được dữ liệu.");
  COURSE=d.course;CONFIG=d.config;
  await loadStudents();
  const start=new Date(CONFIG.start_date+"T00:00:00");
  viewDate=new Date();
  if(viewDate<start)viewDate=new Date(start);
  viewDate.setDate(1);
  renderCalendar();
}
init().catch(e=>document.getElementById("lessonCard").innerHTML=`<div class="placeholder">Lỗi tải ứng dụng: ${e.message}</div>`);
</script>
</body>
</html>
""")
