interface MissingModalityStateProps {
  modality: string;
  description?: string;
}

export function MissingModalityState({ modality, description }: MissingModalityStateProps) {
  return (
    <div className="rounded-lg border border-dashed border-slate-500/60 bg-slate-900/40 p-4 text-sm text-slate-300">
      <p className="font-medium text-slate-200">{modality} not available</p>
      <p className="mt-1">
        {description ??
          "Panel remains visible for transparency. Analysis continues with available modalities only."}
      </p>
    </div>
  );
}
