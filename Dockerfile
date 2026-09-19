FROM python:3.12-slim

# Install system dependencies & umodel requirements
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    wget \
    git \
    libsdl2-2.0-0 \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Install umodel binary
RUN curl -sSL -o /tmp/umodel.tar.gz "https://www.gildor.org/down/47/umodel/umodel_bin.tar.gz" \
    && tar -xzf /tmp/umodel.tar.gz -C /usr/local/bin/ \
    && chmod +x /usr/local/bin/umodel \
    && rm -f /tmp/umodel.tar.gz || true

WORKDIR /app

# Copy dependency specifications
COPY requirements.txt pyproject.toml ./
RUN pip install --no-cache-dir -r requirements.txt

# Copy application source
COPY openrlapi/ ./openrlapi/
COPY README.md LICENSE ./

# Set environment variables
ENV PYTHONUNBUFFERED=1 \
    OPENRL_HOST=0.0.0.0 \
    OPENRL_PORT=8000 \
    OPENRL_DATA_DIR=/app/data \
    OPENRL_THUMBNAILS_DIR=/app/thumbnails

EXPOSE 8000

CMD ["python", "-m", "openrlapi.cli", "serve", "--host", "0.0.0.0", "--port", "8000"]
