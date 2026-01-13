# Use an official Python runtime as a parent image
FROM python:3.11-slim

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV DEBIAN_FRONTEND=noninteractive

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    libopus0 \
    chromium \
    chromium-driver \
    build-essential \
    libffi-dev \
    libssl-dev \
    sqlite3 \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

# Set the working directory in the container
WORKDIR /app

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the application code
COPY . .

# Create necessary directories
RUN mkdir -p Sounds Downloads Data/models/vosk-model-small-pt-0.3 Logs Debug/llm_audio

# Set entry point (can be overridden in docker-compose)
CMD ["python", "PersonalGreeter.py"]
