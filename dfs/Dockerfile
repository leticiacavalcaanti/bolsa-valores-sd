FROM python:3.12-slim
WORKDIR /srv
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY dfs ./dfs
ENV PYTHONUNBUFFERED=1
# Comando padrão: controlador. Os nós e o cliente sobrescrevem o comando no compose.
CMD ["uvicorn", "dfs.controller:app", "--host", "0.0.0.0", "--port", "9000"]
