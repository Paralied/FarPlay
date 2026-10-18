FROM python:3.12-slim
WORKDIR /app
COPY server/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt
COPY server /app/server
COPY web /app/web
RUN useradd --system --uid 10001 farplay
USER farplay
EXPOSE 8080
CMD ["python", "server/app.py"]
