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

from services.dubbing_pipeline import (
    run_pipeline, TTS_VOICE, SUPPORTED_LANGUAGES,
    TARGET_LANGUAGES, TARGET_LANG_CODES, voices_for, default_voice_for,
)

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / '.env')

# MongoDB Baglantisi
mongo_url = os.environ['MONGO_URL']
client = AsyncIOMotorClient(mongo_url)
db = client[os.environ['DB_NAME']]

# Dosya Depolama Alanlari
STORAGE_DIR = Path(os.environ.get("STORAGE_DIR", "/data/dubbing"))
UPLOAD_DIR = STORAGE_DIR / "uploads"
WORK_DIR = STORAGE_DIR / "work"
OUTPUT_DIR = STORAGE_DIR / "outputs"

for d in (UPLOAD_DIR, WORK_DIR, OUTPUT_DIR):
    d.mkdir(parents=True, exist_ok=True)

ALLOWED_EXT = {".mp4", ".mov", ".m4v", ".webm", ".mkv"}

# Ana Uygulama Basligi
app = FastAPI(title="Cok Dilli Dublaj Araci")

# API Router Yapilandirmasi
api_router = APIRouter(prefix="/api")


# ------------------------------------------------------------------
# Veritabanı Modelleri
# ------------------------------------------------------------------
class Segment(BaseModel):
    id: int
    start: float
    end: float
    text_src: str = ""
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
    language: str = "auto"          # kaynak dil
    target_language: str = "tr"     # hedef dublaj dili
    detected_language: str = ""     # whisper'in algiladigi dil
    audio_mode: str = "dub_with_music"  # ses birlesim modu
    duration: float = 0.0
    segments: List[Segment] = Field(default_factory=list)
    output_url: Optional[str] = None
    error: Optional[str] = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


# ------------------------------------------------------------------
# Veritabani Yardimci Fonksiyonlari
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
# Arka Plan Is Akisi Yonetimi
# ------------------------------------------------------------------
def _process_job_sync(job_id: str, video_path: str, voice: str,
                      language: str = "auto", audio_mode: str = "dub_with_music",
                      target_language: str = "tr"):
    """Arka planda calisan ana dublaj thread fonksiyonu."""
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

    succeeded = False
    try:
        sync_db.jobs.update_one(
            {"id": job_id},
            {"$set": {"status": "running", "stage": "extract", "progress": 1,
                      "message": "Baslatiliyor", "updated_at": datetime.now(timezone.utc).isoformat()}},
        )
        out_video = OUTPUT_DIR / f"{job_id}.mp4"
        result = run_pipeline(
            job_id=job_id,
            video_path=Path(video_path),
            work_dir=WORK_DIR / job_id,
            out_video=out_video,
            progress_cb=update,
            voice=voice,
            language=language,
            target_language=target_language,
            audio_mode=audio_mode,
        )
        sync_db.jobs.update_one(
            {"id": job_id},
            {"$set": {
                "status": "done",
                "stage": "done",
                "progress": 100,
                "message": "Tamamlandi",
                "duration": result["duration"],
                "detected_language": result.get("detected_language", ""),
                "target_language": result.get("target_language", target_language),
                "segments": result["segments"],
                "output_url": f"/api/job/{job_id}/download",
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }},
        )
        succeeded = True
    except Exception as e:
        logging.exception("Is akisi sirasinda hata olustu")
        sync_db.jobs.update_one(
            {"id": job_id},
            {"$set": {
                "status": "error",
                "stage": "error",
                "message": "Hata olustu",
                "error": f"{type(e).__name__}: {e}\n{traceback.format_exc()[:1500]}",
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }},
        )
    finally:
        sync_client.close()
        # Basarili olursa gecici klasorleri diskte yer kaplamamasi icin siliyoruz
        if succeeded:
            try:
                work = WORK_DIR / job_id
                if work.exists():
                    shutil.rmtree(work, ignore_errors=True)
            except Exception:
                pass


# ------------------------------------------------------------------
# API Yonlendirmeleri (Routes)
# ------------------------------------------------------------------
@api_router.get("/")
async def root():
    return {"name": "Cok Dilli Dublaj API", "status": "ok"}


@api_router.get("/voices")
async def list_voices(target_lang: str = "tr"):
    voices = voices_for(target_lang)
    return {"voices": voices, "default": (voices[0]["id"] if voices else TTS_VOICE)}


@api_router.get("/target-languages")
async def list_target_languages():
    return {"languages": TARGET_LANGUAGES, "default": "tr"}


@api_router.get("/languages")
async def list_languages():
    return {"languages": SUPPORTED_LANGUAGES, "default": "auto"}


@api_router.get("/audio-modes")
async def list_audio_modes():
    return {
        "modes": [
            {"id": "dub_only",          "name": "Sadece Dublaj",       "description": "Orijinal ses tamamen kaldirilir; arka plan muzigi duyulmaz."},
            {"id": "dub_with_music",    "name": "Dublaj + Arka Plan Muzigi",  "description": "Konusma yapay zeka ile ayristirilir, muzik korunur."},
            {"id": "dub_with_original", "name": "Dublaj + Orijinal Ses",      "description": "Yeni dublaj orijinal sesin uzerine eklenir (orijinal hafif duyulur)."},
        ],
        "default": "dub_with_music",
    }


@api_router.post("/upload")
async def upload_video(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    voice: str = "",
    language: str = "auto",
    target_language: str = "tr",
    audio_mode: str = "dub_with_music",
):
    ext = Path(file.filename).suffix.lower()
    if ext not in ALLOWED_EXT:
        raise HTTPException(400, f"Desteklenmeyen format: {ext}. Kabul edilen: {sorted(ALLOWED_EXT)}")

    valid_codes = {lng["code"] for lng in SUPPORTED_LANGUAGES}
    if language not in valid_codes:
        language = "auto"
    if target_language not in TARGET_LANG_CODES:
        target_language = "tr"
    if audio_mode not in {"dub_only", "dub_with_music", "dub_with_original"}:
        audio_mode = "dub_with_music"
    if not voice:
        voice = default_voice_for(target_language)

    job = Job(filename=file.filename, voice=voice, language=language,
              target_language=target_language,
              audio_mode=audio_mode,
              status="queued", stage="queued",
              progress=0, message="Yukleme alindi")
    save_path = UPLOAD_DIR / f"{job.id}{ext}"
    with save_path.open("wb") as f:
        shutil.copyfileobj(file.file, f)

    await _save_job(job)
    background_tasks.add_task(_process_job_sync, job.id, str(save_path), voice,
                             language, audio_mode, target_language)
    return {"job_id": job.id, "status": job.status, "language": language,
            "target_language": target_language, "audio_mode": audio_mode}


@api_router.get("/job/{job_id}")
async def get_job(job_id: str):
    job = await _get_job(job_id)
    if not job:
        raise HTTPException(404, "Is bulunamadi")
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
        d.pop("segments", None)
        items.append(d)
    return {"items": items}


def _cleanup_job_files(job_id: str):
    """Islem bittiginde diskte artik kalan tum dosyalari temizler."""
    for ext in ALLOWED_EXT:
        p = UPLOAD_DIR / f"{job_id}{ext}"
        if p.exists():
            try:
                p.unlink()
            except Exception:
                pass
    out = OUTPUT_DIR / f"{job_id}.mp4"
    if out.exists():
        try:
            out.unlink()
        except Exception:
            pass
    work = WORK_DIR / job_id
    if work.exists():
        shutil.rmtree(work, ignore_errors=True)


@api_router.get("/job/{job_id}/download")
async def download(job_id: str):
    out = OUTPUT_DIR / f"{job_id}.mp4"
    if not out.exists():
        raise HTTPException(404, "Cikti henuz hazir degil")

    from starlette.background import BackgroundTask

    async def _purge():
        _cleanup_job_files(job_id)
        try:
            await db.jobs.delete_one({"id": job_id})
        except Exception:
            pass

    return FileResponse(
        str(out),
        media_type="video/mp4",
        filename=f"dublaj_{job_id}.mp4",
        background=BackgroundTask(_purge),
    )


@api_router.delete("/job/{job_id}")
async def delete_job(job_id: str):
    job = await _get_job(job_id)
    if not job:
        raise HTTPException(404, "Is bulunamadi")
    await db.jobs.delete_one({"id": job_id})
    _cleanup_job_files(job_id)
    return {"ok": True}


@api_router.post("/jobs/clear-errors")
async def clear_error_jobs():
    cursor = db.jobs.find({"status": "error"}, {"_id": 0, "id": 1})
    ids = [d["id"] async for d in cursor]
    for jid in ids:
        _cleanup_job_files(jid)
    result = await db.jobs.delete_many({"status": "error"})
    return {"deleted": result.deleted_count}


# Sunucu Saglik Kontrolu (Render'in istedigi yol)
@app.get("/health")
async def health():
    return {"ok": True}


app.include_router(api_router)

app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=os.environ.get('CORS_ORIGINS', '*').split(','),
    allow_methods=["*"],
    allow_headers=["*"],
)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


@app.on_event("startup")
async def mark_stale_jobs_on_startup():
    """Sunucu her yeniden basladiginda askida kalan islemleri hata durumuna ceker."""
    try:
        result = await db.jobs.update_many(
            {"status": {"$in": ["queued", "running"]}},
            {"$set": {
                "status": "error",
                "stage": "error",
                "message": "Sunucu yeniden baslatildi - lutfen tekrar yukleyin.",
                "error": "Server restarted during processing.",
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }},
        )
        if result.modified_count:
            logger.warning("Baslangicta askida kalan %d islem temizlendi", result.modified_count)
    except Exception as e:
        logger.warning("Askida kalan isler temizlenirken hata olustu: %s", e)


@app.on_event("shutdown")
async def shutdown_db_client():
    client.close()
