# Dairy Price Checker (FastAPI + vanilla PWA)

Run this on your terminal.

    pip install -r requirements.txt

On Windows PowerShell:

    $env:ADMIN_PASSWORD = "choose-a-strong-password"
    uvicorn main:app --host 0.0.0.0 --port 8000

On macOS or Linux:

    ADMIN_PASSWORD="choose-a-strong-password" uvicorn main:app --host 0.0.0.0 --port 8000

- Farmers: http://localhost:8000/
- Admin:   http://localhost:8000/#/admin  (sign in with the configured ADMIN_PASSWORD)

The app will not start if `ADMIN_PASSWORD` is unset. Use a unique, strong password
and keep it out of source control.

Data lives in `dairy.db` (SQLite, created on first run). Service workers need HTTPS
(or localhost) to install the app on phones, so put it behind a TLS proxy when deploying.