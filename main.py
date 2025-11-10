import os, uuid, json
from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from psycopg_pool import ConnectionPool
from supabase import create_client, Client

# ── 환경변수
SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_SERVICE_KEY = os.environ["SUPABASE_SERVICE_KEY"]
SUPABASE_BUCKET = os.environ.get("SUPABASE_BUCKET", "captures")
DATABASE_URL = os.environ["DATABASE_URL"]  # Supabase Postgres (pooler 권장)
CORS = [o.strip() for o in os.environ.get("CORS_ORIGINS", "*").split(",")]
ALLOW_ORIGINS = ["*"] if CORS == ["*"] else CORS

# ── 클라이언트/풀
supabase: Client = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)
pool = ConnectionPool(conninfo=DATABASE_URL, max_size=5)

# ── 앱/CORS
app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOW_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/api/health")
def health():
    return {"ok": True}

# --------------------------
# 0) 세션 등록
# --------------------------
@app.post("/api/session")
def create_session(session_id: str = Form(...)):
    with pool.connection() as conn:
        with conn.cursor() as cur:
            # sessions(session_id TEXT UNIQUE) 가정
            cur.execute("""
                INSERT INTO sessions (session_id)
                VALUES (%s)
                ON CONFLICT (session_id) DO NOTHING
            """, (session_id,))
            conn.commit()
    return {"ok": True}

# --------------------------
# 1) 페이지1 저장 (프로필)
# --------------------------
@app.post("/api/profile")
def save_profile(
    session_id: str = Form(...),
    nickname: str = Form(...),
    birth_date: str = Form(...),  # "YYYY-MM-DD"
    gender: str = Form(...),      # "male" | "female"
):
    if gender not in ("male","female"):
        raise HTTPException(422, "Invalid gender")

    with pool.connection() as conn:
        with conn.cursor() as cur:
            # 필요 시 profiles(session_id) UNIQUE 제약을 걸면 ON CONFLICT로 upsert 가능
            cur.execute("""
                INSERT INTO profiles (session_id, nickname, birth_date, gender, timestamp_info)
                VALUES (%s,%s,%s,%s, NOW())
            """, (session_id, nickname, birth_date, gender))
            conn.commit()
    return {"ok": True}

# --------------------------
# 2) 페이지2 저장 (피부 설문)
# --------------------------
@app.post("/api/skin")
def save_skin(
    session_id: str = Form(...),
    skin_type: str = Form(...),
    concerns: str = Form("[]"),     # JSON 문자열
    conditions: str = Form("[]"),   # JSON 문자열
):
    # JSON 유효성 체크
    try:
        json.loads(concerns)
        json.loads(conditions)
    except Exception:
        raise HTTPException(422, "Invalid JSON for concerns/conditions")

    with pool.connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO skin_answers (session_id, answers)
                VALUES (%s, %s)
            """, (session_id, json.dumps({
                    "skin_type": skin_type,
                    "concerns": json.loads(concerns),
                    "conditions": json.loads(conditions)
                })))
            conn.commit()
    return {"ok": True}

# --------------------------
# 3) 사진 촬영 업로드 (Storage + DB)
# --------------------------
@app.post("/api/captures")
async def create_capture(
    image: UploadFile = File(...),
    gender: str = Form(...),
    age: int = Form(...),            # 10/20/30/40/50/60/70/80
    session_id: str = Form(None),
    consent: int = Form(1)
):
    if gender not in ("male", "female"):
        raise HTTPException(422, "Invalid gender")
    if age not in (10,20,30,40,50,60,70,80):
        raise HTTPException(422, "Invalid age bucket")

    data = await image.read()
    if not data:
        raise HTTPException(400, "Empty file")

    content_type = image.content_type or "image/jpeg"
    ext = ".jpg" if content_type == "image/jpeg" else ".png"
    filename = f"{uuid.uuid4()}{ext}"

    # 1) Supabase Storage 업로드 (버킷은 public 권장)
    up = supabase.storage.from_(SUPABASE_BUCKET).upload(
        path=filename,
        file=data,
        file_options={"content-type": content_type, "upsert": False},
    )
    if not up or up.get("path") is None:
        raise HTTPException(500, "Storage upload failed")

    # 2) 공개 URL 생성
    image_url = supabase.storage.from_(SUPABASE_BUCKET).get_public_url(filename)

    # 3) DB insert
    with pool.connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO captures (image_url, gender, age_bucket, consent, session_id)
                VALUES (%s,%s,%s,%s,%s)
                RETURNING id
            """, (image_url, gender, age, bool(consent), session_id))
            new_id = cur.fetchone()[0]
            conn.commit()

    return {"ok": True, "id": new_id, "image_url": image_url}
