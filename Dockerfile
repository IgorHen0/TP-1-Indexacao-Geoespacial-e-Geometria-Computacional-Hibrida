FROM python:3.12-slim

WORKDIR /app

# Instala dependências do sistema necessárias para bibliotecas geoespaciais
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

COPY . .

ENV PYTHONPATH=/app
EXPOSE 8050

CMD ["python3", "src/ui/app.py"]
