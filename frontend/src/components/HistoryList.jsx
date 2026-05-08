import React from "react";
import { Trash2, FileVideo, CheckCircle2, Loader2, AlertCircle } from "lucide-react";

const STATUS_LABEL = {
  queued: "Sırada",
  running: "Çalışıyor",
  done: "Tamamlandı",
  error: "Hata",
};

export default function HistoryList({ items, onOpen, onDelete }) {
  if (!items || items.length === 0) {
    return (
      <div className="card-base p-6 text-sm text-muted" data-testid="history-empty">
        Henüz işlem yok. Yukarıdan bir video yükleyin.
      </div>
    );
  }

  return (
    <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4" data-testid="history-grid">
      {items.map((it) => {
        const status = it.status || "queued";
        return (
          <div
            key={it.id}
            className="card-base hoverable p-5 cursor-pointer"
            onClick={() => onOpen(it.id)}
            data-testid={`history-item-${it.id}`}
          >
            <div className="flex items-start justify-between gap-3">
              <div className="flex items-center gap-3 min-w-0">
                <div className="w-10 h-10 rounded-lg bg-[#1A1A1A] border border-[#27272A] flex items-center justify-center shrink-0">
                  <FileVideo className="w-5 h-5 text-[#E63946]" />
                </div>
                <div className="min-w-0">
                  <p className="font-medium truncate text-sm">{it.filename}</p>
                  <p className="text-xs text-muted truncate">{new Date(it.created_at).toLocaleString("tr-TR")}</p>
                </div>
              </div>
              <button
                className="text-muted hover:text-[#E63946] transition"
                onClick={(e) => { e.stopPropagation(); onDelete(it.id); }}
                data-testid={`delete-${it.id}`}
                aria-label="Sil"
              >
                <Trash2 className="w-4 h-4" />
              </button>
            </div>
            <div className="mt-4 flex items-center justify-between">
              <span className="text-xs px-2.5 py-1 rounded-full border border-[#27272A] bg-[#0E0E0E] inline-flex items-center gap-1.5">
                {status === "done" && <CheckCircle2 className="w-3 h-3 text-emerald-500" />}
                {status === "running" && <Loader2 className="w-3 h-3 animate-spin text-[#E63946]" />}
                {status === "error" && <AlertCircle className="w-3 h-3 text-[#E63946]" />}
                {STATUS_LABEL[status] || status}
              </span>
              <span className="text-xs text-muted">{it.progress || 0}%</span>
            </div>
          </div>
        );
      })}
    </div>
  );
}
