# Use official slim Python image
FROM python:3.11-slim

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE 1
ENV PYTHONUNBUFFERED 1

# Set working directory
WORKDIR /app

# Install Python dependencies
COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy backend source code
COPY backend/ .

# Create history directory
RUN mkdir -p data/history

# Expose port
EXPOSE 8000

# Start application (using standard uvicorn without reload for stability)
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
