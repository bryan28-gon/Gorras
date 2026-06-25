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

## Variables para enviar tickets por correo

En local puedes crear un archivo `.env` tomando como base `.env.example`.

En Render agrega estas variables en **Environment Variables**:

```txt
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=tu_correo@gmail.com
SMTP_PASSWORD=tu_contrasena_de_aplicacion
STORE_EMAIL=tu_correo@gmail.com
```

`SMTP_USER` es el correo que envia los tickets. `SMTP_PASSWORD` debe ser una contraseña de aplicacion de Gmail, no la contraseña normal de la cuenta.

## Docker

```bash
docker build -t pos-gorras .
docker run -p 8000:8000 pos-gorras
```

Abrir:

```txt
http://127.0.0.1:8000
```
