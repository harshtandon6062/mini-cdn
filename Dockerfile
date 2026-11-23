FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY origin ./origin
COPY edge ./edge
COPY policy.json .
# Don't run as root inside the container.
RUN useradd --create-home appuser
USER appuser
