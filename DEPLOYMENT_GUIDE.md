# 🚀 AutoSync Dub — Render + MongoDB Atlas Kurulum Talimatı

Bu rehber, projeyi **Emergent ile bağlantısı olmadan** kendi hesabınızda çalıştırmak içindir.
Toplam süre: ~20 dakika. Hepsi **ücretsiz katmanlarda** çalışır.

---

## 🧱 Gereksinimler
- GitHub hesabı (kodu çekmek için)
- MongoDB Atlas hesabı (ücretsiz) — https://www.mongodb.com/cloud/atlas/register
- Render hesabı (ücretsiz) — https://render.com
- OpenAI API anahtarı — https://platform.openai.com/api-keys (≈0.005$/dakika video)

---

## 1️⃣ MongoDB Atlas — Ücretsiz Database Kur

1. https://www.mongodb.com/cloud/atlas/register → Kayıt ol / giriş yap.
2. **"Build a Database"** → **M0 FREE** planı seç → **Provider: AWS**, **Region: Frankfurt** (Türkiye'ye en yakın).
3. **Create**.
4. **Database Access** → **Add New Database User**:
   - Username: `autosync` (örnek)
   - Password: güçlü bir şifre (kopyala bir kenara)
   - Built-in Role: **Atlas admin**
5. **Network Access** → **Add IP Address** → **Allow Access From Anywhere** (`0.0.0.0/0`) → Confirm.
   *(Render dinamik IP kullandığı için bu gerekli.)*
6. **Database** → cluster → **Connect** → **Drivers** → Python:
   ```
   mongodb+srv://autosync:<password>@cluster0.xxxxx.mongodb.net/?retryWrites=true&w=majority
   ```
   `<password>` yerine 4. adımdaki şifreyi yaz. Bu URI'yı **`MONGO_URL`** olarak kaydet.

---

## 2️⃣ OpenAI API Key Al

1. https://platform.openai.com/api-keys → **Create new secret key**.
2. Key'i bir kenara kopyala (`sk-...` ile başlar).
3. Faturalandırma için **Billing** kısmından minimum 5$ kart bilgisi gir (zorunlu, ama 5$ uzun süre yetiyor).

---

## 3️⃣ Kodu GitHub'a At

Eğer kod henüz GitHub'da değilse:

```bash
cd /yol/projeye
git init
git add -A
git commit -m "Initial commit"
git remote add origin https://github.com/KULLANICI_ADINIZ/autosync-dub.git
git push -u origin main
```

*(Veya Emergent Studio'dan **"Save to GitHub"** butonu ile aynı sonucu alırsın.)*

---

## 4️⃣ Render — Backend Service

1. https://dashboard.render.com → **New +** → **Web Service**.
2. GitHub repo'sunu seç.
3. Ayarlar:
   - **Name:** `autosync-dub-backend`
   - **Region:** Frankfurt (EU)
   - **Branch:** `main`
   - **Root Directory:** `backend`
   - **Runtime:** **Docker** (Dockerfile otomatik bulunur)
   - **Instance Type:** **Free** (sonra Starter $7/ay'a yükseltebilirsin)
4. **Environment** sekmesinde şu env'leri ekle:

   | Key | Value |
   |---|---|
   | `MONGO_URL` | (1. adımdan) `mongodb+srv://...` |
   | `DB_NAME` | `autosync_dub` |
   | `EMERGENT_LLM_KEY` | (2. adımdaki OpenAI key) `sk-...` |
   | `WHISPER_MODEL` | `base` (free tier RAM yeterli) |
   | `CORS_ORIGINS` | `*` (sonra frontend URL'i ile sınırla) |
   | `STORAGE_DIR` | `/tmp/dubbing` (free tier disksiz; her restart sonrası temizlenir) |

5. **Health Check Path:** `/health`
6. **Create Web Service** → İlk build 15-20 dakika sürer (Docker image ML kütüphaneleriyle ~3 GB).
7. Bittiğinde URL'i not al: `https://autosync-dub-backend.onrender.com`

> ⚠️ **Free tier uyarısı:** Render free tier 15 dk inactivite sonrası sleep'e girer. Uyandırma 30-60 sn alır. Sürekli açık tutmak istersen **Starter $7/ay** ya da **cron-job.org** ile her 10 dk ping at.

---

## 5️⃣ Render — Frontend Static Site

1. **New +** → **Static Site**.
2. Aynı GitHub repo'sunu seç.
3. Ayarlar:
   - **Name:** `autosync-dub-frontend`
   - **Branch:** `main`
   - **Root Directory:** `frontend`
   - **Build Command:** `yarn install && yarn build`
   - **Publish Directory:** `build`
4. **Environment** sekmesinde:
   | Key | Value |
   |---|---|
   | `REACT_APP_BACKEND_URL` | 4. adımdaki backend URL'i (örn. `https://autosync-dub-backend.onrender.com`) |
5. **Redirects/Rewrites** sekmesi:
   - Source: `/*`
   - Destination: `/index.html`
   - Action: `Rewrite`
   *(React Router'ın çalışması için)*
6. **Create Static Site** → 3-5 dakika içinde canlı.

URL: `https://autosync-dub-frontend.onrender.com`

---

## 6️⃣ Test Et

1. Frontend URL'sini aç.
2. Bir video yükle (örn. Çince konuşma).
3. Pipeline ilerlemesini izle.
4. **MP4 İndir** butonuna bas → indirme bittiğinde **dosya otomatik silinir** (disk koruma için).

---

## 🛡️ İpuçları & Sorun Giderme

### Backend uyumaktan rahatsızsan
- Render Starter $7/ay → uyumaz, daha hızlı CPU.
- Veya cron-job.org → her 10 dakikada `/health` endpoint'ine ping at.

### MongoDB Atlas yer doluyor mu?
- Free M0 = 512 MB. Bu uygulamada sadece job metadata tutuyoruz (~1 KB per job).
- 100.000 job = ~100 MB. Endişeye gerek yok.
- Yedek için: Atlas dashboard → Backup → manuel snapshot.

### OpenAI maliyeti
- GPT-4o ile 2-5 dakikalık bir video çevirisi: **~0.01-0.03 $**.
- Whisper local'de çalıştığı için ekstra maliyet yok (sadece çeviri için OpenAI).

### CORS hatası
- Backend env'inde `CORS_ORIGINS=*` yerine `CORS_ORIGINS=https://autosync-dub-frontend.onrender.com` koy.

### "Application failed to respond" hatası
- Backend container ilk istek geldiğinde 30-60 sn uyanır. Bir kez bekle, sonra tekrar dene.
- Free tier'da Whisper `medium` modeli RAM'e sığmaz. `WHISPER_MODEL=base` veya `tiny` kullan.

### Video dosyaları nerede saklanıyor?
- **Render free tier disksiz** → `/tmp/dubbing` kullanılır → restart sonrası SİLİNİR.
- İndirildikten sonra zaten otomatik siliniyor.
- Kalıcı disk istersen: Starter plana yükselt, `STORAGE_DIR=/var/data/dubbing` yap.

---

## 🎯 Özet — Kontrol Listesi

- [ ] MongoDB Atlas M0 cluster oluşturuldu, `MONGO_URL` kopyalandı
- [ ] OpenAI API key alındı, billing aktif (`sk-...`)
- [ ] Kod GitHub'a push edildi
- [ ] Render Backend Web Service yaratıldı + env'ler ayarlandı
- [ ] Render Frontend Static Site yaratıldı + `REACT_APP_BACKEND_URL` ayarlandı
- [ ] Frontend URL'inden test yapıldı, video indirildi

Hepsi 👍 → **Emergent ile bağlantın artık YOK**. Sistemi tamamen kendi hesabında çalıştırıyorsun.

---

## 💰 Aylık Tahmini Maliyet

| Kaynak | Plan | Ücret |
|---|---|---|
| MongoDB Atlas M0 | Free | **0 $** |
| Render Backend Free | Free (uyur) | **0 $** |
| Render Frontend Static | Free | **0 $** |
| OpenAI GPT-4o | Pay-as-you-go | **~5-10 $/ay** (orta kullanım) |
| **TOPLAM** |  | **~5-10 $/ay** |

İsteğe bağlı upgrade:
- Render Starter Backend: **+7 $/ay** (uyumaz, hızlı)
- Render Persistent Disk 1GB: **+1 $/ay** (videolar oturum arası saklanır)

---

**Hayırlı olsun reis 🎬**
