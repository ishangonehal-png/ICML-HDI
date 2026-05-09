export function ResearchDisclaimerBanner() {
  return (
    <div className="border-b border-amber-300/40 bg-amber-500/15 px-4 py-2 text-center text-xs font-medium text-amber-100">
      Research-only prototype — proxy estimates from public TCGA data. Not for clinical use.
    </div>
  );
}

export function ResearchDisclaimerFooter() {
  return (
    <footer className="border-t border-amber-300/25 bg-slate-900/70 px-4 py-3 text-center text-xs text-amber-100/90">
      Research-only prototype · Outputs are proxy estimates with uncertainty/provenance and no clinical validity claims.
    </footer>
  );
}
