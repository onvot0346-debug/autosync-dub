import React, { useEffect, useRef, useState, useCallback } from "react";
import axios from "axios";
import { toast } from "sonner";
import {
  Upload,
  Download,
  Loader2,
  Trash2,
  FileVideo,
  CheckCircle2,
  AlertCircle,
  Play,
  Mic,
  Languages,
  Music2,
  AudioWaveform,
  Film,
  Wand2,
} from "lucide-react";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Button } from "@/components/ui/button";

// process nesnesinin tanımsız olması durumunda çökmesini önlemek için güvenli kontrol
const getBackendUrl = () => {
  try {
    if (typeof process !== "undefined" && process.env && process.env.REACT_APP_BACKEND_URL) {
      return process.env.REACT_APP_BACKEND_URL;
    }
  } catch (e) {
    // Güvenli hata yakalama
  }
  return "";
};

const BACKEND_URL = getBackendUrl();
const API = `${BACKEND_URL}/api`;

const STAGES = [
  { key: "extract",    label: "Ses Çıkarma",    icon: AudioWaveform },
  { key: "separate",   label: "Vokal Ayrıştırma", icon: Music2 },
  { key: "transcribe", label: "Transkripsiyon",   icon: Mic },
  { key: "translate",  label: "Çeviri",           icon: Languages },
  { key: "tts",        label: "Seslendirme",      icon: Wand2 },
  { key: "mux",        label: "Birleştirme",      icon: Film },
];

// ---------- İÇERİYE GÖMÜLÜ BİLEŞENLER ----------

function StageStepper({ stages, current, isError, isDone, progress, message }) {
  return (
    <div className="space-y-4">
      {stages.map((stage, idx) => {
        const Icon = stage.icon;
        const isCompleted = idx < current || isDone;
        const isActive = idx === current && !isDone && !isError;
        const hasFailed = idx === current && isError;

        let iconColor = "text-muted-foreground";
        let borderColor = "border-[#27272A]";
        let bgClass = "bg-[#1A1A1A]";

        if (isCompleted) {
          iconColor = "text-emerald-500";
          borderColor = "border-emerald-500/50";
          bgClass = "bg-emerald-500/10";
        } else if (isActive) {
          iconColor = "text-[#E63946]";
          borderColor = "border-[#E63946]";
          bgClass = "bg-[#E63946]/10";
        } else if (hasFailed) {
          iconColor = "text-red-500";
          borderColor = "border-red-500/50";
          bgClass = "bg-red-500/10";
        }

        return (
          <div key={stage.key} className="flex items-center gap-3 p-3 rounded-xl border border-[#27272A] bg-[#0E0E0E]">
            <div className={`w-10 h-10 rounded-full border ${borderColor} ${bgClass} flex items-center justify-center`}>
              {isCompleted ? (
                <CheckCircle2 className="w-5 h-5 text-emerald-500" />
              ) : isActive && progress > 0 ? (
                <Loader2 className="w-5 h-5 animate-spin text-[#E63946]" />
              ) : (
                <Icon className={`w-5 h-5 ${iconColor}`} />
              )}
            </div>
            <div className="flex-1">
              <p className="text-sm font-medium">{stage.label}</p>
              {isActive && (
                <div className="mt-1">
                  <div className="w-full bg-[#1A1A1A] rounded-full h-1.5 overflow-hidden">
                    <div className="bg-[#E63946] h-1.5 rounded-full transition-all duration-300" style={{ width: `${progress}%` }} />
                  </div>
                  {message && <p className="text-xs text-[#E63946] mt-1">{message} (%{progress})</p>}
                </div>
              )}
            </div>
          </div>
        );
      })}
    </div>
  );
}

function HistoryList({ items, onOpen, onDelete }) {
  if (!items || items.length === 0) {
    return (
      <div className="p-8 text-center text-muted border border-dashed border-[#27272A] rounded-xl bg-[#0E0E0E]">
        <p>Henüz geçmiş işlem bulunmuyor.</p>
      </div>
    );
  }

  return (
    <div className="overflow-x-auto rounded-xl border border-[#27272A] bg-[#0E0E0E]">
      <table className="w-full text-left border-collapse">
        <thead>
          <tr className="border-b border-[#1A1A1A] text-xs uppercase tracking-wider text-muted font-semibold bg-[#111]">
            <th className="p-4">Dosya Adı</th>
            <th className="p-4">Dil / Mod</th>
            <th className="p-4">Durum</th>
            <th className="p-4">Süre</th>
            <th className="p-4">Tarih</th>
            <th className="p-4 text-right">İşlemler</th>
          </tr>
        </thead>
        <tbody className="text-sm divide-y divide-[#1A1A1A]">
          {items.map((item) => (
            <tr key={item.id} className="hover:bg-[#111] transition-colors">
              <td className="p-4 font-medium flex items-center gap-2">
                <FileVideo className="w-4 h-4 text-[#E63946]" />
                <span className="truncate max-w-[200px]" title={item.filename}>{item.filename}</span>
              </td>
              <td className="p-4">
                <div className="text-xs">
                  <span className="font-semibold">{langLabel(item.detected_language || item.language)}</span>
                  {" → "}
                  <span className="font-semibold text-[#E63946]">{langLabel(item.target_language)}</span>
                </div>
                <div className="text-[10px] text-muted">{audioModeLabel(item.audio_mode)}</div>
              </td>
              <td className="p-4">
                {item.status === "done" && (
                  <span className="inline-flex items-center gap-1 text-emerald-500 text-xs">
                    <CheckCircle2 className="w-3.5 h-3.5" /> Tamamlandı
                  </span>
                )}
                {item.status === "running" && (
                  <span className="inline-flex items-center gap-1 text-[#E63946] text-xs">
                    <Loader2 className="w-3.5 h-3.5 animate-spin" /> {item.message || "İşleniyor"}
                  </span>
                )}
                {item.status === "queued" && (
                  <span className="inline-flex items-center gap-1 text-yellow-500 text-xs">
                    Sırada
                  </span>
                )}
                {item.status === "error" && (
                  <span className="inline-flex items-center gap-1 text-red-500 text-xs">
                    <AlertCircle className="w-3.5 h-3.5" /> Hata
                  </span>
                )}
              </td>
              <td className="p-4 text-muted">{item.duration ? `${item.duration.toFixed(1)} sn` : "—"}</td>
              <td className="p-4 text-xs text-muted">
                {item.created_at ? new Date(item.created_at).toLocaleString("tr-TR") : "—"}
              </td>
              <td className="p-4 text-right">
                <div className="flex items-center justify-end gap-2">
                  <Button
                    size="sm"
                    variant="secondary"
                    onClick={() => onOpen(item.id)}
                    className="h-8 px-3"
                  >
                    Aç
                  </Button>
                  <Button
                    size="sm"
                    variant="destructive"
                    onClick={() => onDelete(item.id)}
                    className="h-8 px-3 bg-red-950 hover:bg-red-900 border border-red-800 text-red-200"
                  >
                    Sil
                  </Button>
                </div>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

// ---------- ANA UYGULAMA BİLEŞENİ ----------

export default function App() {
  const [voices, setVoices] = useState([]);
  const [languages, setLanguages] = useState([]);
  const [targetLanguages, setTargetLanguages] = useState([]);
  const [audioModes, setAudioModes] = useState([]);
  const [selectedVoice, setSelectedVoice] = useState("");
  const [selectedLang, setSelectedLang] = useState("auto");
  const [selectedTargetLang, setSelectedTargetLang] = useState("tr");
  const [selectedMode, setSelectedMode] = useState("dub_with_music");
  const [job, setJob] = useState(null);
  const [history, setHistory] = useState([]);
  const [dragOver, setDragOver] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [clearingErrors, setClearingErrors] = useState(false);
  const fileInputRef = useRef(null);
  const pollRef = useRef(null);

  // ---------- API Çağrıları ----------
  const fetchVoices = useCallback(async (forTarget) => {
    try {
      const tgt = forTarget || "tr";
      const r = await axios.get(`${API}/voices?target_lang=${encodeURIComponent(tgt)}`);
      setVoices(r.data.voices || []);
      if (r.data.default) {
        setSelectedVoice(r.data.default);
      }
    } catch (e) {
      console.error("Ses listesi yuklenirken hata olustu:", e);
    }
  }, []);

  const fetchTargetLanguages = useCallback(async () => {
    try {
      const r = await axios.get(`${API}/target-languages`);
      setTargetLanguages(r.data.languages || []);
      if (r.data.default) setSelectedTargetLang(r.data.default);
    } catch (e) {
      console.error("Hedef diller yuklenirken hata olustu:", e);
    }
  }, []);

  const fetchLanguages = useCallback(async () => {
    try {
      const r = await axios.get(`${API}/languages`);
      setLanguages(r.data.languages || []);
      if (r.data.default) setSelectedLang(r.data.default);
    } catch (e) {
      console.error("Kaynak diller yuklenirken hata olustu:", e);
    }
  }, []);

  const fetchAudioModes = useCallback(async () => {
    try {
      const r = await axios.get(`${API}/audio-modes`);
      setAudioModes(r.data.modes || []);
      if (r.data.default) setSelectedMode(r.data.default);
    } catch (e) {
      console.error("Ses modlari yuklenirken hata olustu:", e);
    }
  }, []);

  const fetchHistory = useCallback(async () => {
    try {
      const r = await axios.get(`${API}/jobs`);
      setHistory(r.data.items || []);
    } catch (e) {
      console.error("Gecmis yuklenirken hata olustu:", e);
    }
  }, []);

  const pollJob = useCallback(async (jobId) => {
    try {
      const r = await axios.get(`${API}/job/${jobId}`);
      setJob(r.data);
      if (r.data.status === "done") {
        toast.success("İşlem tamamlandı! Videonuz indirmeye hazır.");
        clearInterval(pollRef.current);
        pollRef.current = null;
        fetchHistory();
      } else if (r.data.status === "error") {
        toast.error("İşlem sırasında hata oluştu.");
        clearInterval(pollRef.current);
        pollRef.current = null;
        fetchHistory();
      }
    } catch (e) {
      console.error("Is sorgulama hatasi:", e);
    }
  }, [fetchHistory]);

  const startPolling = useCallback((jobId) => {
    if (pollRef.current) clearInterval(pollRef.current);
    pollRef.current = setInterval(() => pollJob(jobId), 1500);
  }, [pollJob]);

  // ---------- Video Yükleme İşlemi ----------
  const handleFile = async (file) => {
    if (!file) return;
    const ok = [".mp4", ".mov", ".m4v", ".webm", ".mkv"].some((e) =>
      file.name.toLowerCase().endsWith(e)
    );
    if (!ok) {
      toast.error("Lütfen MP4, MOV, M4V, WEBM veya MKV formatında bir video yükleyin.");
      return;
    }
    setUploading(true);
    setJob(null);
    const fd = new FormData();
    fd.append("file", file);
    try {
      const r = await axios.post(
        `${API}/upload?voice=${encodeURIComponent(selectedVoice)}&language=${encodeURIComponent(selectedLang)}&target_language=${encodeURIComponent(selectedTargetLang)}&audio_mode=${encodeURIComponent(selectedMode)}`,
        fd,
        { headers: { "Content-Type": "multipart/form-data" } }
      );
      toast.success("Video yüklendi, işleme başlandı.");
      const id = r.data.job_id;
      const initial = await axios.get(`${API}/job/${id}`);
      setJob(initial.data);
      startPolling(id);
      fetchHistory();
    } catch (e) {
      console.error(e);
      const msg = e.response?.data?.detail || "Yükleme başarısız.";
      toast.error(msg);
    } finally {
      setUploading(false);
    }
  };

  const onDrop = (e) => {
    e.preventDefault();
    setDragOver(false);
    const file = e.dataTransfer.files?.[0];
    handleFile(file);
  };

  // ---------- Sayfa Başlangıç Ayarları ----------
  useEffect(() => {
    fetchTargetLanguages();
    fetchLanguages();
    fetchAudioModes();
    fetchHistory();
    return () => { if (pollRef.current) clearInterval(pollRef.current); };
  }, [fetchTargetLanguages, fetchLanguages, fetchAudioModes, fetchHistory]);

  // HEDEF DİL DEĞİŞTİĞİNDE SESLERİ YENİDEN ÇEK
  useEffect(() => {
    if (selectedTargetLang) {
      fetchVoices(selectedTargetLang);
    }
  }, [selectedTargetLang, fetchVoices]);

  const reopenJob = async (id) => {
    const r = await axios.get(`${API}/job/${id}`);
    setJob(r.data);
    if (r.data.status === "running" || r.data.status === "queued") {
      startPolling(id);
    }
  };

  const deleteJob = async (id) => {
    try {
      await axios.delete(`${API}/job/${id}`);
      toast.success("İş silindi.");
      if (job?.id === id) setJob(null);
      fetchHistory();
    } catch (e) {
      toast.error("Silinemedi.");
    }
  };

  const clearErrors = async () => {
    setClearingErrors(true);
    try {
      const r = await axios.post(`${API}/jobs/clear-errors`);
      const n = r.data.deleted || 0;
      if (n > 0) {
        toast.success(`${n} hatalı kayıt temizlendi.`);
      } else {
        toast.info("Temizlenecek hatalı kayıt yok.");
      }
      if (job?.status === "error") setJob(null);
      fetchHistory();
    } catch (e) {
      toast.error("Hatalar temizlenemedi.");
    } finally {
      setClearingErrors(false);
    }
  };

  // ---------- Arayüz Çıktısı ----------
  const currentStageIdx = job ? STAGES.findIndex((s) => s.key === job.stage) : -1;

  return (
    <div className="relative z-10 max-w-7xl mx-auto px-6 py-10 lg:py-14 text-white">
      {/* ---------- Üst Başlık ---------- */}
      <header className="flex items-center justify-between gap-6 mb-12" data-testid="app-header">
        <div className="flex items-center gap-4">
          <div className="seal" aria-hidden>译</div>
          <div>
            <p className="font-display text-xs uppercase tracking-[0.28em] text-muted">
              Dublaj Stüdyosu
            </p>
            <h1 className="font-display text-3xl sm:text-4xl font-bold leading-tight">
              Videoyu <span style={{ color: "#E63946" }}>İstediğin Dile</span> Dublajla
            </h1>
          </div>
        </div>
        <div className="hidden md:flex items-center gap-2 text-xs text-muted">
          <span className="w-2 h-2 rounded-full bg-emerald-500" />
          API çevrim içi
        </div>
      </header>

      {/* ---------- Ana Grid Düzeni ---------- */}
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-6 lg:gap-8">
        {/* Sol Panel: Video Yükleme ve Sonuçlar */}
        <section className="card-base p-8 lg:p-12 col-span-1 lg:col-span-8" data-testid="upload-card">
          <div className="flex items-start justify-between mb-6 gap-4 flex-wrap">
            <div>
              <h2 className="font-display text-2xl font-semibold">Video Yükle</h2>
              <p className="text-sm text-muted mt-1">
                MP4 / MOV / M4V / WEBM (önerilen 2-5 dakika).
              </p>
            </div>
            <div className="flex items-end gap-3 flex-wrap text-black">
              <LanguageSelector
                languages={languages}
                value={selectedLang}
                onChange={setSelectedLang}
                disabled={uploading || (job && job.status === "running")}
                label="Kaynak Dil"
                testId="language-select"
              />
              <TargetLanguageSelector
                languages={targetLanguages}
                value={selectedTargetLang}
                onChange={setSelectedTargetLang}
                disabled={uploading || (job && job.status === "running")}
              />
              <AudioModeSelector
                modes={audioModes}
                value={selectedMode}
                onChange={setSelectedMode}
                disabled={uploading || (job && job.status === "running")}
              />
              <VoiceSelector
                voices={voices}
                value={selectedVoice}
                onChange={setSelectedVoice}
                disabled={uploading || (job && job.status === "running")}
              />
            </div>
          </div>

          <div
            data-testid="upload-zone"
            className={`dropzone rounded-2xl p-10 lg:p-16 text-center cursor-pointer ${
              dragOver ? "drag" : ""
            }`}
            onDragOver={(e) => { e.preventDefault(); setDragOver(true); }}
            onDragLeave={() => setDragOver(false)}
            onDrop={onDrop}
            onClick={() => fileInputRef.current?.click()}
            role="button"
            tabIndex={0}
          >
            <input
              ref={fileInputRef}
              type="file"
              accept="video/mp4,video/quicktime,video/x-m4v,video/webm,video/x-matroska"
              hidden
              onChange={(e) => handleFile(e.target.files?.[0])}
              data-testid="upload-input"
            />
            <div className="flex flex-col items-center gap-4">
              <div className="w-14 h-14 rounded-full bg-[#1A1A1A] border border-[#27272A] flex items-center justify-center">
                {uploading ? (
                  <Loader2 className="w-6 h-6 animate-spin" />
                ) : (
                  <Upload className="w-6 h-6 text-[#E63946]" />
                )}
              </div>
              <div>
                <p className="font-display text-lg font-medium">
                  {uploading ? "Yükleniyor..." : "Video dosyasını buraya bırak veya tıkla"}
                </p>
                <p className="text-sm text-muted mt-1 text-zinc-400">
                  Gemini AI ile Çince, Türkçe, İngilizce og 20+ dilden istediğin dile kusursuz dublaj.
                </p>
              </div>
            </div>
          </div>

          {/* Sonuç Alanı */}
          {job && (
            <div className="mt-10">
              <ResultsView job={job} />
            </div>
          )}
        </section>

        {/* Sağ Panel: İşlem Hattı */}
        <aside className="card-base p-7 col-span-1 lg:col-span-4" data-testid="pipeline-card">
          <p className="font-display text-xs uppercase tracking-[0.24em] text-muted">
            Aşamalar
          </p>
          <h3 className="font-display text-xl font-semibold mt-1 mb-6">İşlem Hattı</h3>
          <StageStepper
            stages={STAGES}
            current={currentStageIdx}
            isError={job?.status === "error"}
            isDone={job?.status === "done"}
            progress={job?.progress || 0}
            message={job?.message || ""}
          />

          {job?.status === "error" && (
            <div className="mt-6 p-4 rounded-lg border border-[#9B2226]/40 bg-[#9B2226]/10 text-sm" data-testid="job-error">
              <div className="flex items-center gap-2 mb-2">
                <AlertCircle className="w-4 h-4 text-[#E63946]" />
                <span className="font-medium">Hata</span>
              </div>
              <p className="text-muted text-xs whitespace-pre-wrap break-words">
                {job.error?.split("\n")[0] || "Bilinmeyen hata"}
              </p>
            </div>
          )}
        </aside>

        {/* Alt Kısım: Geçmiş İşlemler */}
        <section className="col-span-1 lg:col-span-12 mt-6" data-testid="history-section">
          <div className="flex items-end justify-between mb-4">
            <div>
              <p className="font-display text-xs uppercase tracking-[0.24em] text-muted">
                Geçmiş
              </p>
              <h3 className="font-display text-xl font-semibold mt-1">Önceki İşlemler</h3>
            </div>
            <div className="flex items-center gap-2">
              <button
                onClick={clearErrors}
                className="btn-secondary"
                disabled={clearingErrors}
                data-testid="clear-errors-btn"
                title="Tüm hatalı kayıtları sil"
              >
                {clearingErrors ? (
                  <Loader2 className="w-4 h-4 animate-spin" />
                ) : (
                  <Trash2 className="w-4 h-4" />
                )}
                Hataları Temizle
              </button>
              <button onClick={fetchHistory} className="btn-secondary" data-testid="refresh-history-btn">
                Yenile
              </button>
            </div>
          </div>
          <HistoryList items={history} onOpen={reopenJob} onDelete={deleteJob} />
        </section>
      </div>

      <footer className="mt-16 pt-6 border-t border-[#1A1A1A] text-xs text-muted flex items-center justify-between">
        <span>Kendi Altyapın · Whisper · Gemini AI · Edge TTS · Demucs</span>
        <span>© Dublaj Stüdyosu</span>
      </footer>
    </div>
  );
}

/* ---------- Ses Modu Seçimi ---------- */
function AudioModeSelector({ modes, value, onChange, disabled }) {
  const current = modes.find((m) => m.id === value);
  return (
    <div className="flex flex-col gap-1 text-white">
      <label className="text-xs uppercase tracking-[0.18em] text-muted">Ses Modu</label>
      <select
        data-testid="audio-mode-select"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        disabled={disabled}
        title={current?.description || ""}
        className="bg-[#1A1A1A] border border-[#27272A] rounded-lg px-3 py-2 text-sm focus:outline-none focus:border-[#E63946] min-w-[210px] text-white"
      >
        {modes.map((m) => (
          <option key={m.id} value={m.id} className="bg-[#111] text-white">
            {m.name}
          </option>
        ))}
      </select>
    </div>
  );
}

/* ---------- Seslendirici Seçimi ---------- */
function VoiceSelector({ voices, value, onChange, disabled }) {
  return (
    <div className="flex flex-col gap-1 text-white">
      <label className="text-xs uppercase tracking-[0.18em] text-muted">Ses</label>
      <select
        data-testid="voice-select"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        disabled={disabled}
        className="bg-[#1A1A1A] border border-[#27272A] rounded-lg px-3 py-2 text-sm focus:outline-none focus:border-[#E63946] min-w-[140px] text-white"
      >
        {voices.map((v) => (
          <option key={v.id} value={v.id} className="bg-[#111] text-white">
            {v.name}
          </option>
        ))}
      </select>
    </div>
  );
}

/* ---------- Kaynak Dil Seçimi ---------- */
function LanguageSelector({ languages, value, onChange, disabled, label = "Kaynak Dil", testId = "language-select" }) {
  return (
    <div className="flex flex-col gap-1 text-white">
      <label className="text-xs uppercase tracking-[0.18em] text-muted">{label}</label>
      <select
        data-testid={testId}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        disabled={disabled}
        className="bg-[#1A1A1A] border border-[#27272A] rounded-lg px-3 py-2 text-sm focus:outline-none focus:border-[#E63946] min-w-[160px] text-white"
      >
        {languages.map((lng) => (
          <option key={lng.code} value={lng.code} className="bg-[#111] text-white">
            {lng.name}
          </option>
        ))}
      </select>
    </div>
  );
}

/* ---------- Hedef Dil Seçimi ---------- */
function TargetLanguageSelector({ languages, value, onChange, disabled }) {
  return (
    <div className="flex flex-col gap-1 text-white">
      <label className="text-xs uppercase tracking-[0.18em] text-muted">Hedef Dil</label>
      <select
        data-testid="target-language-select"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        disabled={disabled}
        className="bg-[#1A1A1A] border border-[#27272A] rounded-lg px-3 py-2 text-sm focus:outline-none focus:border-[#E63946] min-w-[160px] text-white"
      >
        {languages.map((lng) => (
          <option key={lng.code} value={lng.code} className="bg-[#111] text-white">
            {lng.name}
          </option>
        ))}
      </select>
    </div>
  );
}

/* ---------- Sonuç / Karşılaştırma / Önizleme ---------- */
function ResultsView({ job }) {
  const downloadHref = `${API}/job/${job.id}/download`;
  const isDone = job.status === "done";
  const segs = job.segments || [];

  // Dinamik Kolon Başlıkları için Eşleştirme
  const srcLangName = langLabel(job.detected_language || job.language) || "Kaynak";
  const tgtLangName = langLabel(job.target_language) || "Hedef";

  return (
    <div className="grid grid-cols-1 lg:grid-cols-12 gap-6 mt-2 text-white" data-testid="results-view">
      {/* Sol Sütun: Metin Karşılaştırma */}
      <div className="card-base p-6 col-span-1 lg:col-span-7" data-testid="comparison-card">
        <div className="flex items-center justify-between mb-4">
          <h4 className="font-display text-lg font-semibold">Metin Karşılaştırma</h4>
          <span className="text-xs text-muted">{segs.length} segment</span>
        </div>
        
        {segs.length === 0 ? (
          <EmptyHint text="Transkripsiyon ve çeviri tamamlandığında burada görünecek." />
        ) : (
          <div className="space-y-2">
            {/* Kolon Başlıkları */}
            <div className="grid grid-cols-12 gap-3 px-3 py-1 text-xs uppercase tracking-wider text-muted font-semibold">
              <div className="col-span-12 md:col-span-2">Süre</div>
              <div className="col-span-12 md:col-span-5">{srcLangName} Metin</div>
              <div className="col-span-12 md:col-span-5">{tgtLangName} Çeviri</div>
            </div>

            <ScrollArea className="h-[360px] pr-3">
              <div className="space-y-3">
                {segs.map((s) => (
                  <div key={s.id} className="grid grid-cols-12 gap-3 p-3 rounded-lg border border-[#1F1F22] bg-[#0E0E0E]" data-testid={`segment-${s.id}`}>
                    <div className="col-span-12 md:col-span-2 text-xs text-muted font-mono">
                      {fmtTime(s.start)} → {fmtTime(s.end)}
                    </div>
                    <div className="col-span-12 md:col-span-5 text-sm">
                      {s.text_src || s.text_zh || ""}
                    </div>
                    <div className="col-span-12 md:col-span-5 text-sm">
                      {s.text_tr}
                    </div>
                  </div>
                ))}
              </div>
            </ScrollArea>
          </div>
        )}
      </div>

      {/* Sağ Sütun: Video Önizleme ve İndirme */}
      <div className="card-base p-6 col-span-1 lg:col-span-5" data-testid="preview-card">
        <h4 className="font-display text-lg font-semibold mb-4">Önizleme</h4>
        <div className="aspect-video w-full rounded-xl border border-[#1F1F22] bg-black flex items-center justify-center overflow-hidden">
          {isDone ? (
            <video
              key={job.id}
              src={downloadHref}
              controls
              className="w-full h-full"
              data-testid="result-video"
            />
          ) : (
            <div className="flex flex-col items-center gap-3 text-muted">
              <Play className="w-8 h-8" />
              <span className="text-sm">Hazırlanıyor...</span>
            </div>
          )}
        </div>
        <div className="mt-5 flex items-center justify-between gap-3 flex-wrap">
          <div className="text-xs text-muted">
            {job.duration ? `${job.duration.toFixed(1)} sn` : "—"} · {job.voice}
            {job.detected_language ? ` · ${langLabel(job.detected_language)}` : ""}
            {job.audio_mode ? ` · ${audioModeLabel(job.audio_mode)}` : ""}
          </div>
          <a
            href={isDone ? downloadHref : "#"}
            onClick={(e) => { if (!isDone) e.preventDefault(); }}
            className={`btn-primary ${!isDone ? "opacity-50 pointer-events-none" : ""}`}
            data-testid="download-btn"
          >
            <Download className="w-4 h-4" />
            MP4 İndir
          </a>
        </div>
      </div>
    </div>
  );
}

function EmptyHint({ text }) {
  return (
    <div className="h-[180px] flex items-center justify-center text-sm text-muted border border-dashed border-[#27272A] rounded-lg">
      {text}
    </div>
  );
}

function fmtTime(s) {
  if (s == null) return "00:00";
  const m = Math.floor(s / 60).toString().padStart(2, "0");
  const sec = Math.floor(s % 60).toString().padStart(2, "0");
  return `${m}:${sec}`;
}

const LANG_LABELS = {
  zh: "Çince", vi: "Vietnamca", en: "İngilizce", ja: "Japonca",
  ko: "Korece", ru: "Rusça", ar: "Arapça", fa: "Farsça", hi: "Hintçe",
  id: "Endonezce", th: "Tayca", fr: "Fransızca", de: "Almanca",
  es: "İspanyolca", it: "İtalyanca", pt: "Portekizce", nl: "Hollandaca",
  pl: "Lehçe", uk: "Ukraynaca", tr: "Türkçe",
};
function langLabel(code) {
  if (!code) return "";
  return LANG_LABELS[code] || code.toUpperCase();
}

const AUDIO_MODE_LABELS = {
  dub_only: "Sadece Dublaj",
  dub_with_music: "Dublaj + Müzik",
  dub_with_original: "Dublaj + Orijinal",
};
function audioModeLabel(id) {
  return AUDIO_MODE_LABELS[id] || id;
}
