import React from "react";
import { CheckCircle2, Loader2, AlertCircle } from "lucide-react";

export default function StageStepper({ stages, current, isError, isDone, progress, message }) {
  return (
    <div data-testid="stage-stepper">
      <ol className="space-y-4">
        {stages.map((s, idx) => {
          const status =
            isError && idx === current ? "error" :
            isDone || idx < current ? "done" :
            idx === current ? "active" : "pending";
          const Icon = s.icon;
          return (
            <li key={s.key} className="flex items-center gap-3" data-testid={`stage-${s.key}`}>
              <div className={`stage-dot ${status === "active" ? "active" : ""} ${status === "done" ? "done" : ""}`} />
              <div className={`flex items-center gap-2 ${status === "pending" ? "text-muted" : ""}`}>
                <Icon className={`w-4 h-4 ${status === "active" ? "text-[#E63946]" : ""}`} />
                <span className="text-sm font-medium">{s.label}</span>
              </div>
              <div className="ml-auto">
                {status === "done" && <CheckCircle2 className="w-4 h-4 text-emerald-500" />}
                {status === "active" && <Loader2 className="w-4 h-4 animate-spin text-[#E63946]" />}
                {status === "error" && <AlertCircle className="w-4 h-4 text-[#E63946]" />}
              </div>
            </li>
          );
        })}
      </ol>

      <div className="mt-6">
        <div className="h-1.5 rounded-full bg-[#1A1A1A] overflow-hidden">
          <div
            className="h-full bg-[#E63946] transition-all duration-700"
            style={{ width: `${Math.max(2, progress || 0)}%` }}
            data-testid="progress-bar-fill"
          />
        </div>
        <div className="mt-2 flex items-center justify-between text-xs text-muted">
          <span data-testid="progress-message">{message || "Hazır"}</span>
          <span data-testid="progress-percent">{progress || 0}%</span>
        </div>
      </div>
    </div>
  );
}
