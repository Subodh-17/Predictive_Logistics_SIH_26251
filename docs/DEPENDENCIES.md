# Dependencies

* **Python runtime:** `backend/requirements.in` lists the direct dependencies (ranges); `backend/requirements.txt` is the fully pinned set resolved from it in a clean Python 3.12 virtual environment and used for every V6 verification. `numpy`, `scikit-learn`, `scipy` and `lightgbm` are pinned to the versions the shipped model artefacts were produced with (`ml/requirements-ml.txt`). Install: `pip install -r backend/requirements.txt`.
* **Regenerate the lock:** in a fresh venv, `pip install -r backend/requirements.in`, then `pip freeze` (keep the four ML pins above unless you also retrain), then re-run the test suite and `pip-audit -r backend/requirements.txt --no-deps`. Hash-locking (`pip-compile --generate-hashes`) was attempted but did not finish in the verification environment, so installs are version-pinned, not hash-verified.
* **Test tooling:** `backend/requirements-dev.txt` (pytest, httpx, playwright, pip-audit).
* **Frontend:** `frontend/package-lock.json` (`npm ci`). Node 22 was used.
* **Known advisories:** see `docs/SECURITY_REVIEW.md` (build tooling only).
