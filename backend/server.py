from fastapi import FastAPI, APIRouter, UploadFile, File, BackgroundTasks, HTTPException
from fastapi.responses import FileResponse
from dotenv import load_dotenv
from starlette.middleware.cors import CORSMiddleware
from motor.motor_asyncio import AsyncIOMotorClient
import os
import shutil
import logging
import traceback
from pathlib import Path
from pydantic import BaseModel, Field, ConfigDict
from typing import List, Optional, Any
import uuid
from datetime import datetime, timezone

from services.dubbing_pipeline import run_pipeline, TTS_VOICE


ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / '.env')

# MongoDB connection
mongo_url = os.environ['MONGO_URL']
client = AsyncIOMotorClient(mongo_url)
db = client[os.environ['DB_NAME']]

# Storage
STORAGE_DIR = Path(os.environ.get("STORAGE_DIR", "/data/dubbing"))
UPLOAD_DIR = STORAGE_DIR / "uploads"
WORK_DIR = STORAGE_DIR / "work"
OUTPUT_DIR = STORAGE_DIR / "outputs"
for d in (UPLOAD_DIR, WORK_DIR, OUTPUT_DIR):
    d.mkdir(parents=True, exist_ok=True)

ALLOWED_EXT = {".mp4", ".mov", ".m4v", ".webm", ".mkv"}

# Create the main app without a prefix
app = FastAPI(title="Çince → Türkçe Dublaj Aracı")

# Create a router with the /api prefix
api_router = APIRouter(prefix="/api")


# ------------------------------------------------------------------
# Models
# ------------------------------------------------------------------
class Segment(BaseModel):
    id: int
    start: float
    end: float
    text_zh: str
    text_tr: str = ""


class Job(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    filename: str
    status: str = "queued"  # queued | running | done | error
    stage: str = "queued"   # extract | separate | transcribe | translate | tts | mux | done | error
    progress: int = 0       # 0..100
    message: str = ""
    voice: str = TTS_VOICE
    duration: float = 0.0
    segments: List[Segment] = Field(default_factory=list)
    output_url: Optional[str] = None
    error: Optional[str] = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


# ------------------------------------------------------------------
# DB helpers
# ------------------------------------------------------------------
def _to_doc(job: Job) -> dict:
    doc = job.model_dump()
    doc["created_at"] = doc["created_at"].isoformat()
    doc["updated_at"] = doc["updated_at"].isoformat()
    return doc


def _from_doc(doc: dict) -> Job:
    if isinstance(doc.get("created_at"), str):
        doc["created_at"] = datetime.fromisoformat(doc["created_at"])
    if isinstance(doc.get("updated_at"), str):
        doc["updated_at"] = datetime.fromisoformat(doc["updated_at"])
    return Job(**doc)


async def _save_job(job: Job):
    job.updated_at = datetime.now(timezone.utc)
    await db.jobs.update_one(
        {"id": job.id},
        {"$set": _to_doc(job)},
        upsert=True,
    )


async def _get_job(job_id: str) -> Optional[Job]:
    doc = await db.jobs.find_one({"id": job_id}, {"_id": 0})
    return _from_doc(doc) if doc else None


# ------------------------------------------------------------------
# Background processing
# ------------------------------------------------------------------
def _process_job_sync(job_id: str, video_path: str, voice: str):
    """Runs in a thread (BackgroundTasks). Uses sync MongoDB via pymongo."""
    from pymongo import MongoClient
    sync_client = MongoClient(os.environ["MONGO_URL"])
    sync_db = sync_client[os.environ["DB_NAME"]]

    def update(stage: str, progress: int, message: Optional[str]):
        sync_db.jobs.update_one(
            {"id": job_id},
            {"$set": {
                "stage": stage,
                "progress": progress,
                "message": message or "",
                "status": "running" if stage != "done" else "done",
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }},
        )

    try:
        sync_db.jobs.update_one(
            {"id": job_id},
            {"$set": {"status": "running", "stage": "extract", "progress": 1,
                      "message": "Başlatılıyor", "updated_at": datetime.now(timezone.utc).isoformat()}},
        )
        out_video = OUTPUT_DIR / f"{job_id}.mp4"
        result = run_pipeline(
            job_id=job_id,
            video_path=Path(video_path),
            work_dir=WORK_DIR / job_id,
            out_video=out_video,
            progress_cb=update,
            voice=voice,
        )
        sync_db.jobs.update_one(
            {"id": job_id},
            {"$set": {
                "status": "done",
                "stage": "done",
                "progress": 100,
                "message": "Tamamlandı",
                "duration": result["duration"],
                "segments": result["segments"],
                "output_url": f"/api/job/{job_id}/download",
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }},
        )
    except Exception as e:
        logging.exception("Job failed")
        sync_db.jobs.update_one(
            {"id": job_id},
            {"$set": {
                "status": "error",
                "stage": "error",
                "message": "Hata oluştu",
                "error": f"{type(e).__name__}: {e}\n{traceback.format_exc()[:1500]}",
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }},
        )
    finally:
        sync_client.close()
        # Auto-cleanup work dir to free disk (output + upload kept for download)
        try:
            work = WORK_DIR / job_id
            if work.exists():
                shutil.rmtree(work, ignore_errors=True)
        except Exception:
            pass


# ------------------------------------------------------------------
# Routes
# ------------------------------------------------------------------
@api_router.get("/")
async def root():
    return {"name": "Çince → Türkçe Dublaj API", "status": "ok"}


@api_router.get("/voices")
async def list_voices():
    """Curated short list of Turkish edge-tts voices."""
    return {
        "voices": [
            {"id": "tr-TR-AhmetNeural", "name": "Ahmet (Erkek)", "gender": "male"},
            {"id": "tr-TR-EmelNeural",  "name": "Emel (Kadın)",  "gender": "female"},
        ],
        "default": TTS_VOICE,
    }


@api_router.post("/upload")
async def upload_video(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    voice: str = TTS_VOICE,
):
    ext = Path(file.filename).suffix.lower()
    if ext not in ALLOWED_EXT:
        raise HTTPException(400, f"Desteklenmeyen format: {ext}. Kabul edilen: {sorted(ALLOWED_EXT)}")

    job = Job(filename=file.filename, voice=voice, status="queued", stage="queued",
              progress=0, message="Yükleme alındı")
    save_path = UPLOAD_DIR / f"{job.id}{ext}"
    with save_path.open("wb") as f:
        shutil.copyfileobj(file.file, f)

    await _save_job(job)
    background_tasks.add_task(_process_job_sync, job.id, str(save_path), voice)
    return {"job_id": job.id, "status": job.status}


@api_router.get("/job/{job_id}")
async def get_job(job_id: str):
    job = await _get_job(job_id)
    if not job:
        raise HTTPException(404, "İş bulunamadı")
    return job.model_dump()


@api_router.get("/jobs")
async def list_jobs():
    cursor = db.jobs.find({}, {"_id": 0}).sort("created_at", -1).limit(50)
    items = []
    async for d in cursor:
        if isinstance(d.get("created_at"), str):
            d["created_at"] = datetime.fromisoformat(d["created_at"])
        if isinstance(d.get("updated_at"), str):
            d["updated_at"] = datetime.fromisoformat(d["updated_at"])
        # strip heavy fields for list view
        d.pop("segments", None)
        items.append(d)
    return {"items": items}


@api_router.get("/job/{job_id}/download")
async def download(job_id: str):
    out = OUTPUT_DIR / f"{job_id}.mp4"
    if not out.exists():
        raise HTTPException(404, "Çıktı henüz hazır değil")
    return FileResponse(str(out), media_type="video/mp4",
                        filename=f"dublaj_{job_id}.mp4")


@api_router.delete("/job/{job_id}")
async def delete_job(job_id: str):
    job = await _get_job(job_id)
    if not job:
        raise HTTPException(404, "İş bulunamadı")
    await db.jobs.delete_one({"id": job_id})
    # cleanup files
    for ext in ALLOWED_EXT:
        p = UPLOAD_DIR / f"{job_id}{ext}"
        if p.exists():
            p.unlink()
    out = OUTPUT_DIR / f"{job_id}.mp4"
    if out.exists():
        out.unlink()
    work = WORK_DIR / job_id
    if work.exists():
        shutil.rmtree(work, ignore_errors=True)
    return {"ok": True}


# Include the router in the main app
app.include_router(api_router)

app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=os.environ.get('CORS_ORIGINS', '*').split(','),
    allow_methods=["*"],
    allow_headers=["*"],
)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


@app.on_event("shutdown")
async def shutdown_db_client():
    client.close()
