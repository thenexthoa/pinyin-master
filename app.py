# PINYIN MASTER V6.1
# Monthly calendar + Mon/Wed lessons + 02/09 holiday
# Day 1 = 19/08/2026
# Gemini Developer API only

import os
import json
import re
from dotenv import load_dotenv
from fastapi import FastAPI, UploadFile, File, Form
from fastapi.responses import HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
from google import genai
from google.genai import types

load_dotenv()
API_KEY = os.getenv("GEMINI_API_KEY")
if not API_KEY:
    raise ValueError("Không tìm thấy GEMINI_API_KEY trong file .env")

MODEL = "gemini-3.1-flash-lite"
VERSION = "6.1-product"
client = genai.Client(api_key=API_KEY)

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

COURSE_DATA = {
    "day1": {
        "day": 1,
        "title": "6 nguyên âm đơn",
        "subtitle": "a · o · e · i · u · ü",
        "description": "Làm quen 6 nguyên âm đơn, khinh thanh và biến điệu thanh 3.",
        "items": [
            {"id":"d1_01","hanzi":"八","pinyin":"bā","meaning":"tám","focus":"a"},
            {"id":"d1_02","hanzi":"我","pinyin":"wǒ","meaning":"tôi","focus":"o"},
            {"id":"d1_03","hanzi":"饿","pinyin":"è","meaning":"đói","focus":"e"},
            {"id":"d1_04","hanzi":"一","pinyin":"yī","meaning":"một","focus":"i"},
            {"id":"d1_05","hanzi":"五","pinyin":"wǔ","meaning":"năm","focus":"u"},
            {"id":"d1_06","hanzi":"女","pinyin":"nǚ","meaning":"nữ","focus":"ü"},
            {"id":"d1_07","hanzi":"妈妈","pinyin":"mā ma","meaning":"mẹ","focus":"khinh thanh"},
            {"id":"d1_08","hanzi":"你好","pinyin":"nǐ hǎo","meaning":"xin chào","focus":"biến điệu thanh 3"},
        ],
    },
    "day2": {
        "day": 2,
        "title": "Phụ âm môi",
        "subtitle": "b · p · m · f",
        "description": "Luyện vị trí môi và phân biệt âm bật hơi – không bật hơi.",
        "items": [
            {"id":"d2_01","hanzi":"爸爸","pinyin":"bà ba","meaning":"bố","focus":"b"},
            {"id":"d2_02","hanzi":"跑","pinyin":"pǎo","meaning":"chạy","focus":"p"},
            {"id":"d2_03","hanzi":"妈妈","pinyin":"mā ma","meaning":"mẹ","focus":"m"},
            {"id":"d2_04","hanzi":"房","pinyin":"fáng","meaning":"phòng","focus":"f"},
        ],
    },
    "day3": {
        "day": 3,
        "title": "Thanh điệu",
        "subtitle": "Thanh 1 · Thanh 2",
        "description": "Luyện độ cao và hướng đi của thanh 1 và thanh 2.",
        "items": [
            {"id":"d3_01","hanzi":"妈","pinyin":"mā","meaning":"mẹ","focus":"thanh 1"},
            {"id":"d3_02","hanzi":"麻","pinyin":"má","meaning":"cây gai / tê","focus":"thanh 2"},
        ],
    },
    "day4": {
        "day": 4,
        "title": "Thanh điệu",
        "subtitle": "Thanh 3 · Thanh 4",
        "description": "Luyện thanh thấp và thanh rơi.",
        "items": [
            {"id":"d4_01","hanzi":"马","pinyin":"mǎ","meaning":"ngựa","focus":"thanh 3"},
            {"id":"d4_02","hanzi":"骂","pinyin":"mà","meaning":"mắng","focus":"thanh 4"},
        ],
    },
    "day5": {
        "day": 5,
        "title": "Vận mẫu kép",
        "subtitle": "ai · ei · ao · ou",
        "description": "Luyện chuyển động khẩu hình trong vận mẫu kép.",
        "items": [
            {"id":"d5_01","hanzi":"买","pinyin":"mǎi","meaning":"mua","focus":"ai"},
            {"id":"d5_02","hanzi":"杯","pinyin":"bēi","meaning":"cốc / ly","focus":"ei"},
            {"id":"d5_03","hanzi":"好","pinyin":"hǎo","meaning":"tốt","focus":"ao"},
            {"id":"d5_04","hanzi":"走","pinyin":"zǒu","meaning":"đi","focus":"ou"},
        ],
    },
    "day6": {
        "day": 6,
        "title": "Âm mặt lưỡi",
        "subtitle": "j · q · x",
        "description": "Luyện j, q, x và vị trí mặt lưỡi.",
        "items": [
            {"id":"d6_01","hanzi":"几","pinyin":"jǐ","meaning":"mấy","focus":"j"},
            {"id":"d6_02","hanzi":"请","pinyin":"qǐng","meaning":"mời / xin","focus":"q"},
            {"id":"d6_03","hanzi":"谢","pinyin":"xiè","meaning":"cảm ơn","focus":"x"},
        ],
    },
    "day7": {
        "day": 7,
        "title": "Âm đầu lưỡi sau",
        "subtitle": "zh · ch · sh · r",
        "description": "Luyện nhóm âm đầu lưỡi sau.",
        "items": [
            {"id":"d7_01","hanzi":"中","pinyin":"zhōng","meaning":"trung","focus":"zh"},
            {"id":"d7_02","hanzi":"车","pinyin":"chē","meaning":"xe","focus":"ch"},
            {"id":"d7_03","hanzi":"十","pinyin":"shí","meaning":"mười","focus":"sh"},
            {"id":"d7_04","hanzi":"人","pinyin":"rén","meaning":"người","focus":"r"},
        ],
    },
}

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

def find_item(day_id, item_id):
    lesson = COURSE_DATA.get(day_id)
    if not lesson:
        return None, None
    return lesson, next((x for x in lesson["items"] if x["id"] == item_id), None)

def evaluate_pronunciation(audio_bytes, mime_type, hanzi, pinyin, focus):
    prompt = f"""
Bạn là giáo viên phát âm tiếng Trung phổ thông cho người Việt.

MỤC TIÊU:
Hanzi: {hanzi}
Pinyin: {pinyin}
Trọng tâm: {focus}

Nghe AUDIO THỰC TẾ và so sánh trực tiếp với mục tiêu.
Không chấm đúng chỉ vì nhận ra từ.

Chấm riêng:
- initial_score: 0-10
- final_score: 0-10
- tone_score: 0-10
- overall_score: 0-10

Tone phải dựa vào âm thanh thực tế, không suy từ chữ Hán hoặc từ vựng.
Overall ưu tiên: initial 25%, final 30%, tone 45%.

Feedback bằng tiếng Việt, ngắn, dễ hiểu, có hành động sửa cụ thể.

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

Status chỉ dùng: "Tốt", "Khá", "Cần luyện".
Không markdown.
"""
    response = client.models.generate_content(
        model=MODEL,
        contents=[
            prompt,
            types.Part.from_bytes(data=audio_bytes, mime_type=mime_type),
        ],
        config=types.GenerateContentConfig(
            temperature=0.1,
            response_mime_type="application/json",
        ),
    )
    result = extract_json(response.text)
    for key in ["initial_score", "final_score", "tone_score", "overall_score"]:
        result[key] = score10(result.get(key, 0))
    return result

@app.get("/api/course")
def get_course():
    return {
        "success": True,
        "version": VERSION,
        "course": COURSE_DATA,
        "config": COURSE_CONFIG,
    }

@app.post("/api/evaluate")
async def evaluate(
    audio: UploadFile = File(...),
    day_id: str = Form(...),
    item_id: str = Form(...),
    student_name: str = Form(""),
):
    try:
        lesson, item = find_item(day_id, item_id)
        if not lesson or not item:
            return {"success": False, "error": "Không tìm thấy bài/từ luyện."}
        audio_bytes = await audio.read()
        if len(audio_bytes) < 1000:
            return {"success": False, "error": "Bản ghi quá ngắn. Hãy thử đọc lại."}
        if len(audio_bytes) > 8 * 1024 * 1024:
            return {"success": False, "error": "Bản ghi quá dài."}

        result = evaluate_pronunciation(
            audio_bytes,
            audio.content_type or "audio/webm",
            item["hanzi"],
            item["pinyin"],
            item["focus"],
        )
        return {
            "success": True,
            "version": VERSION,
            "student_name": student_name.strip(),
            "day_id": day_id,
            "day": lesson["day"],
            "item": item,
            "result": result,
        }
    except Exception as error:
        print("EVALUATE ERROR:", repr(error))
        return {"success": False, "error": str(error)}

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
<title>Pinyin Master V6.1</title>
<style>
*{box-sizing:border-box}
:root{--g:#285f4d;--gd:#194839;--gs:#eaf3ef;--light:#f4f8f6;--tx:#20342d;--mu:#7d8c85;--bd:#e1e9e5;--cream:#fff9ec;--red:#a94848}
body{margin:0;background:#f5f7f5;color:var(--tx);font-family:Arial,"Microsoft YaHei","Noto Sans",sans-serif}
button,input{font-family:inherit}.app{max-width:820px;margin:auto;padding:24px 16px 70px}
.header{display:flex;justify-content:space-between;align-items:center;gap:15px;margin-bottom:18px}
.logo-small{font-size:11px;letter-spacing:1.5px;color:var(--mu);margin-bottom:4px}.logo{font-size:26px;font-weight:800;color:var(--gd)}
.student input{min-width:180px;padding:11px 13px;border:1px solid var(--bd);border-radius:12px;outline:none;background:#fff}
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
@media(max-width:600px){.app{padding:17px 10px 55px}.header{align-items:flex-start;flex-direction:column}.student,.student input{width:100%}.card{padding:15px;border-radius:20px}
.week,.calendar{gap:3px}.cell{min-height:67px;padding:6px}.day-badge{font-size:8px}.no-data{font-size:8px}.hanzi{font-size:61px}.actions{grid-template-columns:1fr}}
</style>
</head>
<body>
<div class="app">
<header class="header">
<div><div class="logo-small">THE NEXT HOA</div><div class="logo">Pinyin Master</div></div>
<div class="student"><input id="studentName" placeholder="Tên học viên" autocomplete="name"></div>
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
const studentInput=document.getElementById("studentName");
studentInput.value=localStorage.getItem(STUDENT_KEY)||"";
studentInput.addEventListener("input",()=>localStorage.setItem(STUDENT_KEY,studentInput.value));

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
        html+=`<div class="no-data">Day ${info.day}<br>chưa có bài</div>`;
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
    <div class="lesson-subtitle">${l.subtitle}</div>
    <div class="lesson-description">${l.description}</div>
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
      <div class="result-title">KẾT QUẢ CỦA BẠN</div>
      <div class="overall"><span class="overall-number" id="overallScore">--</span><span class="overall-max">/10</span></div>
      <div class="heard">GEMINI NGHE ĐƯỢC<strong id="heardPinyin">—</strong></div>
      <div class="scores">
        <div class="score-box"><div class="score-value" id="initialScore">--</div><div class="score-name">THANH MẪU</div><div class="score-status" id="initialStatus"></div></div>
        <div class="score-box"><div class="score-value" id="finalScore">--</div><div class="score-name">VẬN MẪU</div><div class="score-status" id="finalStatus"></div></div>
        <div class="score-box"><div class="score-value" id="toneScore">--</div><div class="score-name">THANH ĐIỆU</div><div class="score-status" id="toneStatus"></div></div>
      </div>
      <div class="feedback"><div class="issue" id="mainIssue"></div><div id="feedbackText"></div><div class="enc" id="encouragement"></div></div>
      <div class="next-row"><button class="next" onclick="nextItem()">Tiếp tục →</button></div>
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
  document.getElementById("status").innerText="Nghe mẫu rồi thử đọc";
}

function listenSample(){
  const x=currentItem();if(!x)return;
  speechSynthesis.cancel();
  const u=new SpeechSynthesisUtterance(x.hanzi);u.lang="zh-CN";u.rate=.78;
  const v=speechSynthesis.getVoices().find(v=>v.lang?.toLowerCase().startsWith("zh"));
  if(v)u.voice=v;speechSynthesis.speak(u);
}

async function toggleRecording(){
  if(sending)return;
  const b=document.getElementById("recordButton"),status=document.getElementById("status");
  if(recorder?.state==="recording"){
    recorder.stop();b.innerText="🎙️ Bắt đầu đọc";b.classList.remove("recording");status.innerText="Đang chuẩn bị chấm...";return;
  }
  try{
    mediaStream=await navigator.mediaDevices.getUserMedia({audio:true});audioChunks=[];
    const options=MediaRecorder.isTypeSupported("audio/webm;codecs=opus")?{mimeType:"audio/webm;codecs=opus"}:{};
    recorder=new MediaRecorder(mediaStream,options);
    recorder.ondataavailable=e=>{if(e.data?.size>0)audioChunks.push(e.data)};
    recorder.onstop=async()=>{
      mediaStream?.getTracks().forEach(t=>t.stop());
      const blob=new Blob(audioChunks,{type:recorder.mimeType||"audio/webm"});
      await sendAudio(blob);
    };
    recorder.start();b.innerText="⏹ Dừng & chấm";b.classList.add("recording");
    status.innerText="🔴 Đang nghe bạn đọc...";
    document.getElementById("result").style.display="none";
  }catch(e){status.innerText="Không mở được micro: "+e.message}
}

async function sendAudio(blob){
  const b=document.getElementById("recordButton"),status=document.getElementById("status"),x=currentItem();
  sending=true;b.disabled=true;status.innerText="AI đang nghe và phản hồi...";
  const f=new FormData();
  f.append("audio",blob,"recording.webm");f.append("day_id",currentDayId);f.append("item_id",x.id);f.append("student_name",studentInput.value.trim());
  try{
    const r=await fetch("/api/evaluate",{method:"POST",body:f}),d=await r.json();
    if(!d.success)throw new Error(d.error||"Không chấm được.");
    showResult(d.result);markItemDone(currentDayId,x.id,d.result.overall_score);status.innerText="Đã nhận phản hồi";
  }catch(e){status.innerText="Lỗi: "+e.message}
  finally{sending=false;b.disabled=false}
}

function showResult(r){
  document.getElementById("result").style.display="block";
  document.getElementById("overallScore").innerText=r.overall_score;
  document.getElementById("heardPinyin").innerText=r.heard_pinyin||"—";
  document.getElementById("initialScore").innerText=r.initial_score;
  document.getElementById("finalScore").innerText=r.final_score;
  document.getElementById("toneScore").innerText=r.tone_score;
  document.getElementById("initialStatus").innerText=r.initial_status||"";
  document.getElementById("finalStatus").innerText=r.final_status||"";
  document.getElementById("toneStatus").innerText=r.tone_status||"";
  document.getElementById("mainIssue").innerText=(r.problem_syllable?r.problem_syllable+" · ":"")+(r.main_issue||"Nhận xét");
  document.getElementById("feedbackText").innerText=r.feedback||"";
  document.getElementById("encouragement").innerText=r.encouragement||"";
}

function nextItem(){
  const l=COURSE[currentDayId];
  if(currentItemIndex<l.items.length-1){
    currentItemIndex++;renderItemNav();renderCurrentItem();setTimeout(listenSample,250);
  }else{
    document.getElementById("status").innerText="✓ Bạn đã đi hết nội dung của Day này.";
  }
}

async function init(){
  const d=await(await fetch("/api/course")).json();
  if(!d.success)throw new Error("Không tải được dữ liệu.");
  COURSE=d.course;CONFIG=d.config;
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
