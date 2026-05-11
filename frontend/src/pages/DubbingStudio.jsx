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
import StageStepper from "@/components/StageStepper";
import HistoryList from "@/components/HistoryList";

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL;
const API = `${BACKEND_URL}/api`;

const STAGES = [
  { key: "extract",    label: "Ses Çıkarma",      icon: AudioWaveform },
  { key: "separate",   label: "Vokal Ayrıştırma", icon: Music2 },
  { key: "transcribe", label: "Transkripsiyon",   icon: Mic },
  { key: "translate",  label: "Çeviri",           icon: Languages },
  { key: "tts",        label: "Seslendirme",      icon: Wand2 },
  { key: "mux",        label: "Birleştirme",      icon: Film },
];

export default function DubbingStudio() {
  const [voices, setVoices] = useState([]);
  const [languages, setLanguages] = useState([]);
  const [audioModes, setAudioModes] = useState([]);
  const [selectedVoice, setSelectedVoice] = useState("tr-TR-AhmetNeural");
  const [selectedLang, setSelectedLang] = useState("auto");
  const [selectedMode, setSelectedMode] = useState("dub_with_music");
  const [job, setJob] = useState(null);
  const [history, setHistory] = useState([]);
  const [dragOver, setDragOver] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [clearingErrors, setClearingErrors] = useState(false);
  const fileInputRef = useRef(null);
  const pollRef = useRef(null);

  // ---------- API ----------
  const fetchVoices = useCallback(async () => {
    try {
      const r = await axios.get(`${API}/voices`);
      setVoices(r.data.voices || []);
      if (r.data.default) setSelectedVoice(r.data.default);
    } catch (e) {
      console.error(e);
    }
  }, []);

  const fetchLanguages = useCallback(async () => {
    try {
      const r = await axios.get(`${API}/languages`);
      setLanguages(r.data.languages || []);
      if (r.data.default) setSelectedLang(r.data.default);
    } catch (e) {
      console.error(e);
    }
  }, []);

  const fetchHistory = useCallback(async () => {
    try {
      const r = await axios.get(`${API}/jobs`);
      setHistory(r.data.items || []);
    } catch (e) {
      console.error(e);
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
      console.error(e);
    }
  }, [fetchHistory]);

  const startPolling = useCallback((jobId) => {
    if (pollRef.current) clearInterval(pollRef.current);
    pollRef.current = setInterval(() => pollJob(jobId), 1500);
  }, [pollJob]);

  // ---------- Upload ----------
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
        `${API}/upload?voice=${encodeURIComponent(selectedVoice)}&language=${encodeURIComponent(selectedLang)}&audio_mode=${encodeURIComponent(selectedMode)}`,
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

  // ---------- Lifecycle ----------
  useEffect(() => {
    fetchVoices();
    fetchLanguages();
    fetchAudioModes();
    fetchHistory();
    return () => { if (pollRef.current) clearInterval(pollRef.current); };
  }, [fetchVoices, fetchLanguages, fetchAudioModes, fetchHistory]);

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

  // ---------- UI ----------
  const currentStageIdx = job ? STAGES.findIndex((s) => s.key === job.stage) : -1;

  return (
    <div className="relative z-10 max-w-7xl mx-auto px-6 py-10 lg:py-14">
      {/* ---------- Header ---------- */}
      <header className="flex items-center justify-between gap-6 mb-12" data-testid="app-header">
        <div className="flex items-center gap-4">
          <div className="seal" aria-hidden>译</div>
          <div>
            <p className="font-display text-xs uppercase tracking-[0.28em] text-muted">
              Dublaj Stüdyosu
            </p>
            <h1 className="font-display text-3xl sm:text-4xl font-bold leading-tight">
              Videoyu <span style={{ color: "#E63946" }}>Türkçe</span> Dublajla
            </h1>
          </div>
        </div>
        <div className="hidden md:flex items-center gap-2 text-xs text-muted">
          <span className="w-2 h-2 rounded-full bg-emerald-500" />
          API çevrim içi
        </div>
      </header>

      {/* ---------- Main grid ---------- */}
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-6 lg:gap-8">
        {/* Upload */}
        <section className="card-base p-8 lg:p-12 col-span-1 lg:col-span-8" data-testid="upload-card">
          <div className="flex items-start justify-between mb-6 gap-4 flex-wrap">
            <div>
              <h2 className="font-display text-2xl font-semibold">Video Yükle</h2>
              <p className="text-sm text-muted mt-1">
                MP4 / MOV / M4V / WEBM (önerilen 2-5 dakika).
              </p>
            </div>
            <div className="flex items-end gap-3 flex-wrap">
              <LanguageSelector
                languages={languages}
                value={selectedLang}
                onChange={setSelectedLang}
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
                <p className="text-sm text-muted mt-1">
                  Çince, Vietnamca, İngilizce ve 20+ dilde otomatik Türkçe dublaj.
                </p>
              </div>
            </div>
          </div>

          {/* When job exists, render preview / segments */}
          {job && (
            <div className="mt-10">
              <ResultsView job={job} />
            </div>
          )}
        </section>

        {/* Pipeline */}
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

        {/* History */}
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
        <span>Tamamen yerel işleme · Whisper · Edge TTS · Demucs</span>
        <span>© Dublaj Stüdyosu</span>
      </footer>
    </div>
  );
}

/* ---------- Audio mode select ---------- */
function AudioModeSelector({ modes, value, onChange, disabled }) {
  const current = modes.find((m) => m.id === value);
  return (
    <div className="flex flex-col gap-1">
      <label className="text-xs uppercase tracking-[0.18em] text-muted">Ses Modu</label>
      <select
        data-testid="audio-mode-select"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        disabled={disabled}
        title={current?.description || ""}
        className="bg-[#1A1A1A] border border-[#27272A] rounded-lg px-3 py-2 text-sm focus:outline-none focus:border-[#E63946] min-w-[210px]"
      >
        {modes.map((m) => (
          <option key={m.id} value={m.id}>
            {m.name}
          </option>
        ))}
      </select>
    </div>
  );
}

/* ---------- Voice select ---------- */
function VoiceSelector({ voices, value, onChange, disabled }) {
  return (
    <div className="flex flex-col gap-1">
      <label className="text-xs uppercase tracking-[0.18em] text-muted">Ses</label>
      <select
        data-testid="voice-select"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        disabled={disabled}
        className="bg-[#1A1A1A] border border-[#27272A] rounded-lg px-3 py-2 text-sm focus:outline-none focus:border-[#E63946] min-w-[140px]"
      >
        {voices.map((v) => (
          <option key={v.id} value={v.id}>
            {v.name}
          </option>
        ))}
      </select>
    </div>
  );
}

/* ---------- Language select ---------- */
function LanguageSelector({ languages, value, onChange, disabled }) {
  return (
    <div className="flex flex-col gap-1">
      <label className="text-xs uppercase tracking-[0.18em] text-muted">Kaynak Dil</label>
      <select
        data-testid="language-select"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        disabled={disabled}
        className="bg-[#1A1A1A] border border-[#27272A] rounded-lg px-3 py-2 text-sm focus:outline-none focus:border-[#E63946] min-w-[160px]"
      >
        {languages.map((lng) => (
          <option key={lng.code} value={lng.code}>
            {lng.name}
          </option>
        ))}
      </select>
    </div>
  );
}

/* ---------- Results / Preview / Segments ---------- */
function ResultsView({ job }) {
  const downloadHref = `${API}/job/${job.id}/download`;
  const isDone = job.status === "done";
  const segs = job.segments || [];

  return (
    <div className="grid grid-cols-1 lg:grid-cols-12 gap-6 mt-2" data-testid="results-view">
      {/* Side-by-side translation */}
      <div className="card-base p-6 col-span-1 lg:col-span-7" data-testid="comparison-card">
        <div className="flex items-center justify-between mb-4">
          <h4 className="font-display text-lg font-semibold">Metin Karşılaştırma</h4>
          <span className="text-xs text-muted">{segs.length} segment</span>
        </div>
        {segs.length === 0 ? (
          <EmptyHint text="Transkripsiyon ve çeviri tamamlandığında burada görünecek." />
        ) : (
          <ScrollArea className="h-[360px] pr-3">
            <div className="space-y-3">
              {segs.map((s) => (
                <div key={s.id} className="grid grid-cols-12 gap-3 p-3 rounded-lg border border-[#1F1F22] bg-[#0E0E0E]" data-testid={`segment-${s.id}`}>
                  <div className="col-span-12 md:col-span-2 text-xs text-muted font-mono">
                    {fmtTime(s.start)} → {fmtTime(s.end)}
                  </div>
                  <div className="col-span-12 md:col-span-5 font-zh text-sm">{s.text_src || s.text_zh || ""}</div>
                  <div className="col-span-12 md:col-span-5 text-sm">{s.text_tr}</div>
                </div>
              ))}
            </div>
          </ScrollArea>
        )}
      </div>

      {/* Preview + download */}
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
  dub_only: "Sadece Türkçe",
  dub_with_music: "Türkçe + Müzik",
  dub_with_original: "Türkçe + Orijinal",
};
function audioModeLabel(id) {
  return AUDIO_MODE_LABELS[id] || id;
}
