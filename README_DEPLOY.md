# Deploy del POS de gorras

Este proyecto corre localmente con FastAPI y SQLite.

## Local

```powershell
pip install -r requirements.txt
python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8003
```

Abrir:

```txt
http://127.0.0.1:8003
```

## Render

Archivos incluidos:

- `render.yaml`
- `Procfile`
- `runtime.txt`

En Render puedes crear un Web Service desde el repositorio. El comando de arranque es:

```bash
uvicorn app.main:app --host 0.0.0.0 --port $PORT
```

Nota: SQLite funciona para una demo, pero en plataformas gratuitas el archivo `pos.db` puede perder cambios si el servicio se reinicia. Para una app real conviene usar PostgreSQL.

## Docker

```bash
docker build -t pos-gorras .
docker run -p 8000:8000 pos-gorras
```

Abrir:

```txt
http://127.0.0.1:8000
```
