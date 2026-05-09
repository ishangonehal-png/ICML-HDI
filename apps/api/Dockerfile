FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /workspace

COPY apps/api/requirements.txt apps/api/requirements.txt
RUN python -m pip install --upgrade pip \
    && python -m pip install -r apps/api/requirements.txt

COPY models/survival_fused_matched /workspace/models/survival_fused_matched
COPY data/luad/fused_pathology_rna_embeddings_with_metadata.csv /workspace/data/luad/

COPY apps/api apps/api

EXPOSE 8000

CMD ["uvicorn", "main:app", "--app-dir", "apps/api", "--host", "0.0.0.0", "--port", "8000"]
