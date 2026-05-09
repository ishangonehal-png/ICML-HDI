"use client";

import { useMemo, useRef, useState } from "react";

import type { UploadModality } from "@/lib/api-client";
import { cn } from "@/lib/utils";

export interface SelectedUploadFile {
  id: string;
  name: string;
  size: number;
  modality: UploadModality;
  file: File;
}

interface UploaderProps {
  files: SelectedUploadFile[];
  onFilesChange: (files: SelectedUploadFile[]) => void;
}

const modalityLabels: Record<UploadModality, string> = {
  pathology: "Pathology",
  transcriptomics: "Transcriptomics",
  clinical: "Clinical",
};

function detectModality(fileName: string): UploadModality {
  const lower = fileName.toLowerCase();
  if (lower.endsWith(".svs") || lower.endsWith(".tif") || lower.endsWith(".tiff")) {
    return "pathology";
  }
  if (lower.endsWith(".tsv") || lower.endsWith(".csv")) {
    return "transcriptomics";
  }
  return "clinical";
}

function toSelectedFiles(fileList: FileList): SelectedUploadFile[] {
  return Array.from(fileList).map((file) => ({
    id: `${file.name}-${file.size}-${file.lastModified}`,
    name: file.name,
    size: file.size,
    modality: detectModality(file.name),
    file,
  }));
}

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  if (bytes < 1024 * 1024 * 1024) return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  return `${(bytes / (1024 * 1024 * 1024)).toFixed(1)} GB`;
}

export function Uploader({ files, onFilesChange }: UploaderProps) {
  const inputRef = useRef<HTMLInputElement | null>(null);
  const [isDragging, setIsDragging] = useState(false);

  const modalityCoverage = useMemo(() => {
    const present = new Set(files.map((file) => file.modality));
    return {
      pathology: present.has("pathology"),
      transcriptomics: present.has("transcriptomics"),
      clinical: present.has("clinical"),
    };
  }, [files]);

  const appendFiles = (incoming: SelectedUploadFile[]) => {
    const byId = new Map(files.map((entry) => [entry.id, entry]));
    for (const item of incoming) {
      byId.set(item.id, item);
    }
    onFilesChange(Array.from(byId.values()));
  };

  const onDrop = (event: React.DragEvent<HTMLDivElement>) => {
    event.preventDefault();
    setIsDragging(false);

    if (!event.dataTransfer.files?.length) return;
    appendFiles(toSelectedFiles(event.dataTransfer.files));
  };

  return (
    <div className="space-y-4">
      <div
        onDragOver={(event) => {
          event.preventDefault();
          setIsDragging(true);
        }}
        onDragLeave={() => setIsDragging(false)}
        onDrop={onDrop}
        className={cn(
          "rounded-xl border border-dashed p-6 text-center transition",
          isDragging ? "border-cyan-300 bg-cyan-500/10" : "border-shell-border bg-slate-900/40",
        )}
      >
        <h3 className="text-sm font-semibold text-slate-100">Drop WSI/RNA/clinical files here</h3>
        <p className="mt-1 text-xs text-slate-300">Supported examples: .svs, .tsv, .xml/.txt/.pdf</p>
        <button
          type="button"
          className="mt-4 rounded-md bg-cyan-500 px-3 py-2 text-xs font-semibold text-slate-900 hover:bg-cyan-400"
          onClick={() => inputRef.current?.click()}
        >
          Browse files
        </button>

        <input
          ref={inputRef}
          type="file"
          multiple
          className="hidden"
          onChange={(event) => {
            if (!event.target.files?.length) return;
            appendFiles(toSelectedFiles(event.target.files));
            event.currentTarget.value = "";
          }}
        />
      </div>

      <div className="flex flex-wrap gap-2 text-xs">
        {(Object.keys(modalityCoverage) as UploadModality[]).map((modality) => (
          <span
            key={modality}
            className={cn(
              "rounded-full border px-2 py-1",
              modalityCoverage[modality]
                ? "border-emerald-300/60 bg-emerald-500/15 text-emerald-100"
                : "border-slate-600 bg-slate-800 text-slate-300",
            )}
          >
            {modalityLabels[modality]} {modalityCoverage[modality] ? "detected" : "missing"}
          </span>
        ))}
      </div>

      <div className="space-y-2">
        {files.length === 0 ? (
          <p className="text-xs text-slate-400">No files selected yet.</p>
        ) : (
          files.map((file) => (
            <div key={file.id} className="flex items-center justify-between rounded-lg border border-shell-border bg-slate-900/30 px-3 py-2">
              <div>
                <p className="text-sm text-slate-100">{file.name}</p>
                <p className="text-xs text-slate-400">{formatBytes(file.size)}</p>
              </div>
              <span className="rounded-full border border-cyan-300/40 bg-cyan-500/10 px-2 py-1 text-[11px] text-cyan-100">
                {modalityLabels[file.modality]}
              </span>
            </div>
          ))
        )}
      </div>
    </div>
  );
}
