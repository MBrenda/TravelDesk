FROM python:3.13-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY requirements.txt constraints.txt ./
RUN pip install --no-cache-dir -r requirements.txt && useradd --uid 10001 --create-home traveldesk && mkdir /data && chown traveldesk /data
COPY --chown=traveldesk:traveldesk app.py ./
COPY --chown=traveldesk:traveldesk static ./static
USER traveldesk
ENV TRAVELDESK_DB=/data/traveldesk.sqlite
EXPOSE 8000
CMD ["python", "app.py", "serve", "--host", "0.0.0.0"]
