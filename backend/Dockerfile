FROM python:3.9-slim

WORKDIR /app

# Install runtime utilities required in container (e.g., curl for health checks)
# and build prerequisites for packages that ship native extensions (cryptography,
# python-snappy, psutil, etc.).
RUN apt-get update && apt-get install -y --no-install-recommends \
        curl \
        build-essential \
        libsnappy-dev \
        libffi-dev \
        libssl-dev \
        pkg-config \
        rustc \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first for better caching
COPY requirements.txt .

# Install dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy all backend files
COPY . .

# Expose port
EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=30s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# Run the FastAPI application with uvicorn
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
