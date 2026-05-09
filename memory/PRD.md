# Çince → Türkçe Otomatik Dublaj Aracı — PRD

## Original Problem Statement
Çince kısa videoları (2-5 dakika) otomatik olarak Türkçe dublajlı hale getiren web tabanlı bir araç. Workflow: Kullanıcı videoyu yükler → Çince ses metne dökülür → Türkçe'ye çevrilir → Türkçe TTS ile seslendirilir → Orijinal arka plan müziği korunarak senkronize edilir → İndirilebilir MP4 olarak sunulur. Modern, minimalist, tamamen Türkçe panel.

## User Choices (kullanıcı onayladı)
- API/anahtar gerektirmeyen, tamamen ücretsiz yığın.
- Whisper (transkripsiyon), deep-translator/Google free (çeviri), edge-tts (TTS — `tr-TR-AhmetNeural` erkek), demucs + ffmpeg fallback (vokal/müzik), ffmpeg (mux).
- Koyu tema, modern minimalist, tamamen Türkçe.
- Kayıt/giriş gerekmiyor.

## Architecture
- **Backend (FastAPI):** `/api/upload` (POST), `/api/job/{id}` (GET), `/api/jobs` (GET), `/api/job/{id}/download` (GET), `/api/voices` (GET), `/api/job/{id}` (DELETE). Pipeline çalışır BackgroundTasks içinde sync MongoDB istemcisi ile.
- **Pipeline (`services/dubbing_pipeline.py`):** ffmpeg → demucs (fallback: orijinal audio + -10dB music kopyası) → whisper (`base`, lang=zh) → deep-translator (zh-CN→tr) + glossary → edge-tts → librosa time-stretch → pydub overlay → ffmpeg amix + mux.
- **Storage:** `/app/backend/storage/{uploads,work,outputs}`.
- **Frontend (React + shadcn/ui):** Tek sayfa `DubbingStudio`. Drag-and-drop yükleme, 6 aşamalı stepper (StageStepper), segment karşılaştırma (Çince/Türkçe yan yana), önizleme oynatıcı + MP4 indirme, geçmiş işlemler grid'i.
- **MongoDB:** `jobs` koleksiyonu (id, filename, status, stage, progress, segments, output_url, timestamps).

## What's Implemented (2026-02)
- [x] Tüm pipeline aşamaları çalışıyor.
- [x] **GPT-4o ile bağlam-aware çeviri** (Emergent Universal Key) — tüm transkript tek seferde, mühendislik/teknik terimler korunarak çevriliyor. Hata durumunda `deep-translator` fallback.
- [x] **Whisper `medium`** (769 MB) — yüksek kalite Çince transkripsiyon, mühendislik terim ipuçlu (initial_prompt) prompt.
- [x] 6-aşamalı progress stepper, Türkçe arayüz, koyu tema, vermilion (kırmızı) Çin mührü esintili tasarım.
- [x] Segment-bazlı time-stretch ile orijinal süreye senkronizasyon (0.7-1.6x clamp).
- [x] **Persistent ffmpeg/ffprobe** via `static-ffmpeg` (venv kalıcı, container restart sonrası bile çalışır).
- [x] Mühendislik terim sözlüğü (`glossary.py`).
- [x] Geçmiş işlemler listesi + silme + tekrar açma.

## Known Limitations / Backlog (P1/P2)
- P1: Demucs kurulumu (torchcodec gereksinimi) sorunlu, fallback mekanizması (orijinal sesi -10dB kullanma) devrede. Gerçek müzik/vokal ayrıştırması için torchaudio<2.5 + demucs upgrade önerilir.
- P1: Whisper `base` modeli Çince transkripsiyon için orta düzey — `medium` veya `small` daha iyi sonuç verir (ama yavaşlar).
- P2: Çoklu eş zamanlı iş kuyruğu yönetimi (şu an FastAPI BackgroundTasks; production için Celery/RQ önerilir).
- P2: 2-5 dakikadan uzun videolar için chunk işleme.
- P2: Yapay zeka tabanlı bağlam-aware çeviri için isteğe bağlı OpenAI GPT-4o entegrasyonu (kullanıcı şu an istemedi).

## Test Credentials
Bu uygulama auth gerektirmez. Kullanıcı doğrudan ana sayfadan kullanır.
