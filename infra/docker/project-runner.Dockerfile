FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# The sandbox can run small PyTorch research models, but cannot download model weights or packages
# at runtime. Keep the runner CPU-only and separate from the API's Python environment.
ARG TORCH_INDEX=https://download.pytorch.org/whl/cpu
RUN pip install torch --index-url ${TORCH_INDEX} \
    && pip install "docker>=7,<8" "fastapi>=0.115,<1" "numpy>=1.26,<3" "uvicorn>=0.30,<1"

COPY infra/runner/manager.py /opt/runner/manager.py
COPY infra/runner/execute.py /opt/runner/execute.py
WORKDIR /workspace
CMD ["uvicorn", "manager:app", "--app-dir", "/opt/runner", "--host", "0.0.0.0", "--port", "8081"]
