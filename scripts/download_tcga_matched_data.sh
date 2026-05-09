#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
BUILD_SCRIPT="$SCRIPT_DIR/build_tcga_matched_cohort.py"

# Fixed dataset definition (no CLI options by design):
# - Project: TCGA-LUAD
# - open RNA-seq: Transcriptome Profiling + Gene Expression Quantification + RNA-Seq + STAR - Counts
# - open slides: WSI/SVS
# - open clinical reports: Clinical Supplement (TXT) + Clinical Supplement (XML) + Pathology Report
# - deterministic patient-level match performed by build_tcga_matched_cohort.py
PROJECT="TCGA-LUAD"
EXPECTED_COHORT_CASES=475

# Full manifest has 1901 files for all modalities (RNA + H&E + Context).
# Expected manifest rows by requested modality selection:
# - RNA only: 475
# - H&E only: 475
# - Context only: 951
# - RNA + H&E: 950
# - RNA + Context: 1426
# - H&E + Context: 1426
# - RNA + H&E + Context: 1901

DEFAULT_OUTPUT_DIR="$REPO_ROOT/hansons-context/tcga_downloads"
OUTPUT_DIR="$DEFAULT_OUTPUT_DIR"
COHORT_PATH=""
MANIFEST_PATH=""
DATA_DIR=""

usage() {
  cat <<USAGE
Usage: scripts/download_tcga_matched_data.sh [--rna] [--he|--slide] [--context] [--output-root PATH]

If no flags are provided, all modalities are downloaded.

Options:
  --output-root PATH  Override output root (default: $DEFAULT_OUTPUT_DIR)

Examples:
  --rna                Download only RNA files
  --he, --slide        Download only H&E SVS files
  --context            Download only contextual files (Pathology Report + Clinical XML + Clinical TXT)
  --rna --context      Download RNA + context only
  --he --context       Download H&E + context only
  --output-root data/custom-downloads --rna --he
USAGE
}

WITH_RNA=false
WITH_SLIDE=false
WITH_CONTEXT=false

while [[ $# -gt 0 ]]; do
  case "$1" in
    --rna)
      WITH_RNA=true
      shift
      ;;
    --he|--slide)
      WITH_SLIDE=true
      shift
      ;;
    --context)
      WITH_CONTEXT=true
      shift
      ;;
    --output-root)
      if [[ $# -lt 2 ]]; then
        echo "ERROR: --output-root requires a path value."
        usage
        exit 1
      fi
      OUTPUT_DIR="$2"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "ERROR: unknown argument '$1'."
      usage
      exit 1
      ;;
  esac
done

COHORT_PATH="$OUTPUT_DIR/tcga_luad_exact_matched_cohort.csv"
MANIFEST_PATH="$OUTPUT_DIR/tcga_luad_exact_matched_manifest.tsv"
DATA_DIR="$OUTPUT_DIR/files"

mkdir -p "$OUTPUT_DIR"
mkdir -p "$DATA_DIR"

# If no flags supplied, download all modalities.
if ! "$WITH_RNA" && ! "$WITH_SLIDE" && ! "$WITH_CONTEXT"; then
  WITH_RNA=true
  WITH_SLIDE=true
  WITH_CONTEXT=true
fi

if ! command -v python3 >/dev/null 2>&1; then
  echo "ERROR: python3 not found."
  exit 1
fi

if ! command -v gdc-client >/dev/null 2>&1; then
  echo "ERROR: gdc-client not found. Install the GDC Data Transfer Tool and retry."
  exit 1
fi

# Always rebuild the manifest from the same fixed query so it does not depend on caller settings.
python3 "$BUILD_SCRIPT" \
  --project "$PROJECT" \
  --out-csv "$COHORT_PATH" \
  --out-manifest "$MANIFEST_PATH"

if [[ ! -s "$MANIFEST_PATH" ]]; then
  echo "ERROR: manifest is empty or missing: $MANIFEST_PATH"
  exit 1
fi

# Make file ordering deterministic for reproducible downloads.
python3 - "$MANIFEST_PATH" <<'PY'
import csv
import sys

path = sys.argv[1]
with open(path, newline="", encoding="utf-8") as f:
    rows = list(csv.reader(f, delimiter="\t"))

if len(rows) <= 1:
    raise SystemExit("ERROR: manifest contains no file rows")

header = rows[0]
data = sorted(rows[1:], key=lambda r: r[0] if r else "")
with open(path, "w", newline="", encoding="utf-8") as f:
    writer = csv.writer(f, delimiter="\t")
    writer.writerow(header)
    writer.writerows(data)
PY

# Filter the manifest to selected modalities.
python3 - "$MANIFEST_PATH" "$WITH_RNA" "$WITH_SLIDE" "$WITH_CONTEXT" <<'PY'
import csv
import sys

manifest_path, with_rna, with_slide, with_context = sys.argv[1:5]
with_rna = with_rna == "true"
with_slide = with_slide == "true"
with_context = with_context == "true"


def modality(filename: str) -> str:
    name = filename.lower()
    if name.endswith(".svs"):
        return "slide"
    if name.endswith(".tsv"):
        return "rna"
    if name.endswith(".pdf") or name.endswith(".xml") or name.endswith(".txt"):
        return "context"
    return "other"

with open(manifest_path, newline="", encoding="utf-8") as f:
    reader = list(csv.DictReader(f, delimiter="\t"))

filtered = [
    r
    for r in reader
    if (with_rna and modality(r["filename"]) == "rna")
    or (with_slide and modality(r["filename"]) == "slide")
    or (with_context and modality(r["filename"]) == "context")
]

with open(manifest_path, "w", newline="", encoding="utf-8") as f:
    writer = csv.DictWriter(f, fieldnames=["id", "filename", "md5", "size", "state"], delimiter="\t")
    writer.writeheader()
    writer.writerows(filtered)
PY

COHORT_ROWS="$(( $(wc -l < "$COHORT_PATH") - 1 ))"
MANIFEST_ROWS="$(( $(wc -l < "$MANIFEST_PATH") - 1 ))"

read -r RNA_ROWS SLIDE_ROWS PDF_ROWS XML_ROWS TXT_ROWS OTHER_ROWS < <(
  python3 - "$MANIFEST_PATH" <<'PY'
import csv
import sys

manifest_path = sys.argv[1]
counts = {
    "rna": 0,
    "slide": 0,
    "pdf": 0,
    "xml": 0,
    "txt": 0,
    "other": 0,
}

with open(manifest_path, newline="", encoding="utf-8") as f:
    rows = csv.DictReader(f, delimiter="\t")
    for row in rows:
        name = row["filename"].lower()
        if name.endswith(".tsv"):
            counts["rna"] += 1
        elif name.endswith(".svs"):
            counts["slide"] += 1
        elif name.endswith(".pdf"):
            counts["pdf"] += 1
        elif name.endswith(".xml"):
            counts["xml"] += 1
        elif name.endswith(".txt"):
            counts["txt"] += 1
        else:
            counts["other"] += 1

print(
    counts["rna"],
    counts["slide"],
    counts["pdf"],
    counts["xml"],
    counts["txt"],
    counts["other"],
)
PY
)

if [[ "$COHORT_ROWS" -ne "$EXPECTED_COHORT_CASES" ]]; then
  echo "ERROR: exact dataset drift detected."
  echo "Expected $EXPECTED_COHORT_CASES matched cases in cohort CSV, got $COHORT_ROWS."
  echo "Refusing to download because this script is locked to the fixed snapshot used for the demo."
  exit 1
fi

if [[ "$WITH_RNA" == true && "$WITH_SLIDE" == true && "$WITH_CONTEXT" == true ]]; then
  EXPECTED_MANIFEST_ROWS=1901
elif [[ "$WITH_RNA" == true && "$WITH_SLIDE" == true ]]; then
  EXPECTED_MANIFEST_ROWS=950
elif [[ "$WITH_RNA" == true && "$WITH_CONTEXT" == true ]]; then
  EXPECTED_MANIFEST_ROWS=1426
elif [[ "$WITH_SLIDE" == true && "$WITH_CONTEXT" == true ]]; then
  EXPECTED_MANIFEST_ROWS=1426
elif [[ "$WITH_RNA" == true ]]; then
  EXPECTED_MANIFEST_ROWS=475
elif [[ "$WITH_SLIDE" == true ]]; then
  EXPECTED_MANIFEST_ROWS=475
elif [[ "$WITH_CONTEXT" == true ]]; then
  EXPECTED_MANIFEST_ROWS=951
else
  echo "ERROR: no modality selected."
  exit 1
fi

if [[ "$MANIFEST_ROWS" -ne "$EXPECTED_MANIFEST_ROWS" ]]; then
  echo "ERROR: exact dataset drift detected for selected modalities."
  echo "Expected $EXPECTED_MANIFEST_ROWS file rows in manifest, got $MANIFEST_ROWS."
  echo "Refusing to download because this script is locked to the fixed snapshot used for the demo." 
  exit 1
fi

EXPECTED_RNA_ROWS=0
EXPECTED_SLIDE_ROWS=0
EXPECTED_PDF_ROWS=0
EXPECTED_XML_ROWS=0
EXPECTED_TXT_ROWS=0

if [[ "$WITH_RNA" == true ]]; then
  EXPECTED_RNA_ROWS=475
fi
if [[ "$WITH_SLIDE" == true ]]; then
  EXPECTED_SLIDE_ROWS=475
fi
if [[ "$WITH_CONTEXT" == true ]]; then
  EXPECTED_PDF_ROWS=475
  EXPECTED_XML_ROWS=475
  EXPECTED_TXT_ROWS=1
fi

if [[ "$RNA_ROWS" -ne "$EXPECTED_RNA_ROWS" ]] || \
   [[ "$SLIDE_ROWS" -ne "$EXPECTED_SLIDE_ROWS" ]] || \
   [[ "$PDF_ROWS" -ne "$EXPECTED_PDF_ROWS" ]] || \
   [[ "$XML_ROWS" -ne "$EXPECTED_XML_ROWS" ]] || \
   [[ "$TXT_ROWS" -ne "$EXPECTED_TXT_ROWS" ]] || \
   [[ "$OTHER_ROWS" -ne 0 ]]; then
  echo "ERROR: manifest composition drift detected for selected modalities."
  echo "Expected counts: RNA=$EXPECTED_RNA_ROWS H&E=$EXPECTED_SLIDE_ROWS PDF=$EXPECTED_PDF_ROWS XML=$EXPECTED_XML_ROWS TXT=$EXPECTED_TXT_ROWS OTHER=0"
  echo "Observed counts: RNA=$RNA_ROWS H&E=$SLIDE_ROWS PDF=$PDF_ROWS XML=$XML_ROWS TXT=$TXT_ROWS OTHER=$OTHER_ROWS"
  echo "Refusing to download because this script is locked to the fixed snapshot used for the demo."
  exit 1
fi

SELECTED=()
if [[ "$WITH_RNA" == true ]]; then
  SELECTED+=("RNA")
fi
if [[ "$WITH_SLIDE" == true ]]; then
  SELECTED+=("H&E")
fi
if [[ "$WITH_CONTEXT" == true ]]; then
  SELECTED+=("Context")
fi

echo "Cohort CSV: $COHORT_PATH"
echo "Manifest:   $MANIFEST_PATH"
echo "Selected:  ${SELECTED[*]}"
echo "Data root:  $DATA_DIR"

# Ensure the downloaded folder is exactly this run's dataset.
rm -rf "$DATA_DIR"
mkdir -p "$DATA_DIR"

gdc-client download --resume -m "$MANIFEST_PATH" -d "$DATA_DIR"
