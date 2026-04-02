# utils/io.py  (exemple de fichier utilitaire)
import json
import os
import tempfile
import logging

logger = logging.getLogger("agent_qa.io")

def write_json_atomic(path: str, obj) -> None:
    """
    Écrit `obj` en JSON dans `path` de façon atomique.
    - crée un fichier temporaire dans le même dossier,
    - dump JSON avec indent pour lisibilité,
    - remplace le fichier cible par os.replace (atomique),
    - valide en relisant le fichier et en faisant json.load.
    Lève une exception en cas d'erreur.
    """
    dirpath = os.path.dirname(path) or "."
    os.makedirs(dirpath, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(prefix=".tmp_", dir=dirpath, text=True)
    os.close(fd)
    try:
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(obj, f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())
        # validation rapide
        with open(tmp_path, "r", encoding="utf-8") as f:
            json.load(f)
        # atomically replace
        os.replace(tmp_path, path)
        logger.info("Wrote JSON atomically to %s", path)
    except Exception as e:
        # cleanup temp file if present
        try:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
        except Exception:
            pass
        logger.exception("Failed to write JSON to %s: %s", path, e)
        raise

def safe_serialize_artifacts(artifacts) -> dict:
    """
    Ensure artifacts is a JSON-serializable dict.
    Convert non-serializable values to strings and keep structure.
    """
    try:
        json.dumps(artifacts)
        return artifacts if isinstance(artifacts, dict) else {"value": artifacts}
    except Exception:
        # fallback: stringify leaves
        def _convert(v):
            try:
                json.dumps(v)
                return v
            except Exception:
                return str(v)
        if isinstance(artifacts, dict):
            return {k: _convert(v) for k, v in artifacts.items()}
        return {"raw": str(artifacts)}
