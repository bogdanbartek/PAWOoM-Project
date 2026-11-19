# Scooter Rental Service (LAB1-LAB2, LAB5): FastAPI + SQLite (wolumen /data) + Redis + RabbitMQ.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Najpierw tylko zależności: zmiana kodu nie wymusza ponownego pip install (cache warstw).
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app

# /data to punkt montowania nazwanego wolumenu z plikiem SQLite (DATABASE_URL=sqlite:////data/app.db).
# Katalog tworzymy PRZED przełączeniem na appuser i oddajemy mu w posiadanie, żeby nowy wolumen
# odziedziczył uprawnienia i SQLite mógł tworzyć app.db oraz pliki dziennika.
RUN adduser --disabled-password --gecos "" appuser \
    && mkdir -p /data \
    && chown -R appuser:appuser /app /data
USER appuser

EXPOSE 8101

CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8101"]
