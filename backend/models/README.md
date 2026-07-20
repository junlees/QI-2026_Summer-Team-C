# models

Place the crop-disease diagnosis model here.

- Model code (loading, preprocessing, inference) goes in this folder.
- Large weight files should **not** be committed — download them at build time
  or load from object storage, and keep the paths in `.gitignore`.
- `backend/app.py` exposes `POST /api/diagnose` as the entry point to wire in.
