from fastapi import FastAPI, UploadFile, File, Form, Request
from fastapi.middleware.cors import CORSMiddleware
from uuid import uuid4
# import os, pymysql, json
from dotenv import load_dotenv
from fastapi.staticfiles import StaticFiles
from urllib.parse import quote

load_dotenv()
app = FastAPI()

origins = os.getenv("ALLOWED_ORIGINS", "*")
allow_origins = ["*"] if origins == "*" else [o.strip() for o in origins.split(",")]

app.add_middleware(
    CORSMiddleware,
    allow_origins=allow_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

def get_conn():
    return pymysql.connect(
        host=os.getenv("MYSQL_HOST"),
        port=int(os.getenv("MYSQL_PORT", "3306")),
        user=os.getenv("MYSQL_USER"),
        password=os.getenv("MYSQL_PASS"),
        database=os.getenv("MYSQL_DB"),
        charset="utf8mb4",
        autocommit=True,
    )

UPLOAD_DIR = os.getenv("UPLOAD_DIR", "./uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)

# 업로드 폴더를 /uploads 경로로 서빙
app.mount("/uploads", StaticFiles(directory=UPLOAD_DIR), name="uploads")

# 0) 세션 등록(최초 진입 시 1회)
@app.post("/api/session")
def create_session(session_id: str = Form(...)):
    conn = get_conn()
    with conn.cursor() as cur:
        cur.execute("INSERT IGNORE INTO sessions(id) VALUES (%s)", (session_id,))
    return {"ok": True}

# 1) 페이지1 저장
@app.post("/api/profile")
def save_profile(
    session_id: str = Form(...),
    nickname: str = Form(...),
    birth_date: str = Form(...),  # "YYYY-MM-DD"
    gender: str = Form(...),      # "male" | "female"
):
    conn = get_conn()
    with conn.cursor() as cur:
        cur.execute("INSERT IGNORE INTO sessions(id) VALUES (%s)", (session_id,))
        cur.execute("""
            INSERT INTO profiles(session_id, nickname, birth_date, gender)
            VALUES (%s,%s,%s,%s)
            ON DUPLICATE KEY UPDATE
              nickname=VALUES(nickname),
              birth_date=VALUES(birth_date),
              gender=VALUES(gender)
        """, (session_id, nickname, birth_date, gender))
    return {"ok": True}

# 2) 페이지2 저장
@app.post("/api/skin")
def save_skin(
    session_id: str = Form(...),
    skin_type: str = Form(...),
    concerns: str = Form("[]"),   # JSON string
    conditions: str = Form("[]"), # JSON string
):
    # 유효성 약간 확인
    json.loads(concerns); json.loads(conditions)
    conn = get_conn()
    with conn.cursor() as cur:
        cur.execute("""
          INSERT INTO skin_answers(session_id, skin_type, concerns, conditions)
          VALUES (%s,%s,%s,%s)
          ON DUPLICATE KEY UPDATE
            skin_type=VALUES(skin_type),
            concerns=VALUES(concerns),
            conditions=VALUES(conditions)
        """, (session_id, skin_type, concerns, conditions))
    return {"ok": True}

@app.post("/api/captures")
async def create_capture(
    request: Request,
    image: UploadFile = File(...),
    gender: str = Form(...),
    age: int = Form(...),
    session_id: str = Form(None),   # ★ 추가
    consent: int = Form(1)
):
  if gender not in ("male", "female"):
      return {"ok": False, "error": "invalid gender"}

  if age not in (10,20,30,40,50,60,70,80):  # 필요에 맞게 수정
      return {"ok": False, "error": "invalid age bucket"}

  if image.content_type not in ("image/jpeg", "image/png"):
      return {"ok": False, "error": "invalid file type"}

  ext = ".jpg" if image.content_type == "image/jpeg" else ".png"
  filename = f"{uuid4()}{ext}"
  path = os.path.join(UPLOAD_DIR, filename)
  with open(path, "wb") as f:
      f.write(await image.read())

  conn = get_conn()
  with conn.cursor() as cur:
      cur.execute(
          "INSERT INTO captures(image_path, gender, age_bucket, consent, session_id) VALUES(%s,%s,%s,%s,%s)",
          (filename, gender, age, consent, session_id)
      )
      new_id = cur.lastrowid

      # 여기에 추가 ⬇
      base = str(request.base_url).rstrip("/")       # 예: http://127.0.0.1:12345
      image_url = f"{base}/uploads/{quote(filename)}"

  return {"ok": True, "id": new_id, "image_path": filename, "image_url": image_url}
