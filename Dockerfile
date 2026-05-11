FROM python:3.11-slim

# Install Node.js for the Wrangler CLI and fonts for OG image generation
RUN apt-get update \
    && apt-get install -y --no-install-recommends nodejs npm fonts-dejavu-core \
    && npm install -g wrangler@4.86.0 \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python dependencies first (cached layer unless requirements change)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code, page template, and static site
COPY publish_temperature.py .
COPY templates/ templates/
COPY site/ site/

RUN useradd -r -u 1000 -m appuser && chown -R appuser:appuser /app
USER appuser

CMD ["python", "publish_temperature.py"]
