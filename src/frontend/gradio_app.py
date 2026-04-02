# src/frontend/gradio_app.py
"""
Gradio frontend for Agent QA & Test Automation.

Features:
- Upload a repository (zip) to the FastAPI backend
- Trigger analysis, test generation and test runs
- Poll for run results and display artifacts, logs and coverage
- Simple, self-contained UI suitable for local development

Notes:
- This frontend uses synchronous HTTP calls (requests). For production, consider
  async clients or websockets for real-time logs.
- Configure API_BASE to point to your FastAPI backend (e.g., http://localhost:8000).
"""

from __future__ import annotations

import io
import json
import os
import threading
import time
from typing import Optional

import gradio as gr
import requests

API_BASE = os.environ.get("API_BASE", "http://localhost:8000")
UPLOAD_ENDPOINT = f"{API_BASE}/api/upload-repo"
ANALYZE_ENDPOINT = f"{API_BASE}/api/analyze"
GENERATE_ENDPOINT = f"{API_BASE}/api/generate-tests"
RUN_ENDPOINT = f"{API_BASE}/api/run-tests"
REPORT_ENDPOINT = f"{API_BASE}/api/report"

# Simple HTTP helpers


def _post_file(url: str, file_bytes: bytes, filename: str = "repo.zip") -> dict:
    files = {"file": (filename, io.BytesIO(file_bytes), "application/zip")}
    resp = requests.post(url, files=files, timeout=120)
    resp.raise_for_status()
    return resp.json()


def _post_json(url: str, payload: dict) -> dict:
    resp = requests.post(url, json=payload, timeout=120)
    resp.raise_for_status()
    return resp.json()


def _get_json(url: str) -> dict:
    resp = requests.get(url, timeout=60)
    resp.raise_for_status()
    return resp.json()


# UI actions


def upload_repo(file_obj) -> dict:
    """
    Upload a zip file to the backend and return repo_id and message.
    """
    if file_obj is None:
        return {"repo_id": "", "message": "Aucun fichier fourni"}
    try:
        file_bytes = file_obj.read()
        data = _post_file(UPLOAD_ENDPOINT, file_bytes, filename=getattr(file_obj, "name", "repo.zip"))
        return {"repo_id": data.get("repo_id", ""), "message": data.get("message", "OK")}
    except Exception as e:
        return {"repo_id": "", "message": f"Upload failed: {e}"}


def analyze_repo(repo_id: str, entrypoint: str | None = None) -> dict:
    if not repo_id:
        return {"analysis_id": "", "summary": "repo_id manquant"}
    payload = {"repo_id": repo_id}
    if entrypoint:
        payload["entrypoint"] = entrypoint
    try:
        data = _post_json(ANALYZE_ENDPOINT, payload)
        return {"analysis_id": data.get("analysis_id", ""), "summary": data.get("summary", "")}
    except Exception as e:
        return {"analysis_id": "", "summary": f"Analyse échouée: {e}"}


def generate_tests(analysis_id: str, target: str = "all", coverage_goal: float = 0.8) -> dict:
    if not analysis_id:
        return {"tests_id": "", "files_generated": 0, "message": "analysis_id manquant"}
    payload = {"analysis_id": analysis_id, "target": target, "coverage_goal": coverage_goal}
    try:
        data = _post_json(GENERATE_ENDPOINT, payload)
        return {"tests_id": data.get("tests_id", ""), "files_generated": data.get("files_generated", 0), "message": "Tests générés"}
    except Exception as e:
        return {"tests_id": "", "files_generated": 0, "message": f"Génération échouée: {e}"}


def run_tests(tests_id: str, timeout_seconds: Optional[int] = None) -> dict:
    if not tests_id:
        return {"run_id": "", "status": "tests_id manquant"}
    payload = {"tests_id": tests_id}
    if timeout_seconds:
        payload["timeout_seconds"] = int(timeout_seconds)
    try:
        data = _post_json(RUN_ENDPOINT, payload)
        return {"run_id": data.get("run_id", ""), "status": data.get("status", "scheduled")}
    except Exception as e:
        return {"run_id": "", "status": f"Run scheduling failed: {e}"}


def poll_run_report(run_id: str, poll_interval: float = 2.0, timeout: float = 300.0) -> dict:
    """
    Poll the report endpoint until a final status is available or timeout.
    Returns the final report dict or an error dict.
    """
    start = time.time()
    while True:
        try:
            report = _get_json(f"{REPORT_ENDPOINT}/{run_id}")
            status = report.get("status", "unknown")
            if status in ("completed", "failed", "error"):
                return report
            # keep polling
        except requests.HTTPError as he:
            # 404 may mean not ready yet; continue polling
            if he.response.status_code == 404:
                pass
            else:
                return {"error": f"HTTP error while polling: {he}"}
        except Exception as e:
            return {"error": f"Polling failed: {e}"}
        if time.time() - start > timeout:
            return {"error": "Polling timeout"}
        time.sleep(poll_interval)


# Gradio UI layout and callbacks


def build_ui():
    with gr.Blocks(title="Agent QA & Test Automation", css=".gradio-container { max-width: 1100px; }") as demo:
        gr.Markdown("## Agent QA & Test Automation — Interface de démonstration")
        with gr.Row():
            with gr.Column(scale=2):
                repo_file = gr.File(label="Upload repository (zip)", file_types=[".zip"])
                upload_btn = gr.Button("Uploader le repo")
                repo_id_out = gr.Textbox(label="Repo ID", interactive=False)
                upload_msg = gr.Textbox(label="Message", interactive=False)

                gr.Markdown("### Analyse")
                entrypoint = gr.Textbox(label="Entrypoint (optionnel)", placeholder="ex: src/main.py")
                analyze_btn = gr.Button("Analyser le repo")
                analysis_id_out = gr.Textbox(label="Analysis ID", interactive=False)
                analysis_summary = gr.Textbox(label="Résumé d'analyse", interactive=False)

                gr.Markdown("### Génération de tests")
                target_dropdown = gr.Dropdown(choices=["unit", "integration", "api", "all"], value="all", label="Type de tests")
                coverage_slider = gr.Slider(minimum=0.1, maximum=1.0, step=0.05, value=0.8, label="Objectif de couverture")
                gen_btn = gr.Button("Générer les tests")
                tests_id_out = gr.Textbox(label="Tests ID", interactive=False)
                files_generated_out = gr.Number(label="Fichiers générés", interactive=False)

                gr.Markdown("### Exécution des tests")
                timeout_input = gr.Number(label="Timeout (s)", value=120)
                run_btn = gr.Button("Lancer les tests")
                run_id_out = gr.Textbox(label="Run ID", interactive=False)
                run_status_out = gr.Textbox(label="Statut", interactive=False)

            with gr.Column(scale=3):
                gr.Markdown("### Logs / Résultats")
                logs = gr.Textbox(label="Logs / Rapport final", lines=20, interactive=False)
                artifacts_dropdown = gr.Dropdown(choices=[], label="Artifacts disponibles", interactive=True)
                download_btn = gr.Button("Télécharger l'artifact sélectionné")
                artifact_link = gr.Textbox(label="Chemin artifact (serveur)", interactive=False)

        # Callbacks wiring

        def on_upload(file_obj):
            res = upload_repo(file_obj)
            repo_id_out.value = res.get("repo_id", "")
            upload_msg.value = res.get("message", "")
            return repo_id_out, upload_msg

        upload_btn.click(fn=on_upload, inputs=[repo_file], outputs=[repo_id_out, upload_msg])

        def on_analyze(repo_id, entrypoint_val):
            res = analyze_repo(repo_id, entrypoint_val or None)
            analysis_id_out.value = res.get("analysis_id", "")
            analysis_summary.value = res.get("summary", "")
            return analysis_id_out, analysis_summary

        analyze_btn.click(fn=on_analyze, inputs=[repo_id_out, entrypoint], outputs=[analysis_id_out, analysis_summary])

        def on_generate(analysis_id, target, coverage):
            res = generate_tests(analysis_id, target=target, coverage_goal=float(coverage))
            tests_id_out.value = res.get("tests_id", "")
            files_generated_out.value = res.get("files_generated", 0)
            return tests_id_out, files_generated_out

        gen_btn.click(fn=on_generate, inputs=[analysis_id_out, target_dropdown, coverage_slider], outputs=[tests_id_out, files_generated_out])

        def on_run(tests_id, timeout_s):
            res = run_tests(tests_id, timeout_seconds=int(timeout_s) if timeout_s else None)
            run_id = res.get("run_id", "")
            run_id_out.value = run_id
            run_status_out.value = res.get("status", "scheduled")

            # Start background thread to poll report and update logs/artifacts
            def _poll_and_update(rid):
                report = poll_run_report(rid)
                if "error" in report:
                    run_status_out.value = "error"
                    logs.value = report.get("error")
                    return
                run_status_out.value = report.get("status", "unknown")
                summary = report.get("summary") or ""
                artifacts = report.get("artifacts") or {}
                # Update logs and artifacts dropdown
                logs.value = json.dumps(summary, ensure_ascii=False, indent=2) if isinstance(summary, (dict, list)) else str(summary)
                # artifacts is a dict name->path; present keys
                artifact_names = list(artifacts.keys())
                # Update UI elements from main thread via gradio's queue mechanism by setting values
                artifacts_dropdown.update(choices=artifact_names, value=artifact_names[0] if artifact_names else None)
                # set artifact link to first artifact path if exists
                if artifact_names:
                    artifact_link.value = artifacts.get(artifact_names[0], "")
                else:
                    artifact_link.value = ""

            thread = threading.Thread(target=_poll_and_update, args=(run_id,), daemon=True)
            thread.start()

            return run_id_out, run_status_out, logs, artifacts_dropdown, artifact_link

        run_btn.click(fn=on_run, inputs=[tests_id_out, timeout_input], outputs=[run_id_out, run_status_out, logs, artifacts_dropdown, artifact_link])

        def on_select_artifact(run_id, artifact_name):
            if not run_id or not artifact_name:
                return ""
            try:
                # Request orchestrator for artifact path (this endpoint returns metadata)
                report = _get_json(f"{REPORT_ENDPOINT}/{run_id}")
                artifacts = report.get("artifacts", {})
                path = artifacts.get(artifact_name, "")
                return path
            except Exception as e:
                return f"Erreur récupération artifact: {e}"

        artifacts_dropdown.change(fn=on_select_artifact, inputs=[run_id_out, artifacts_dropdown], outputs=[artifact_link])

        def on_download_artifact(path_str):
            if not path_str:
                return "Aucun artifact sélectionné"
            # Provide instructions: the backend exposes a download endpoint; we return the direct URL for the user to fetch.
            # If the artifact path is a server-side path, the backend should provide a download endpoint /api/report/{run_id}/artifact/{name}
            return f"Utilisez l'endpoint backend pour télécharger: {path_str}"

        download_btn.click(fn=on_download_artifact, inputs=[artifact_link], outputs=[logs])

    return demo


if __name__ == "__main__":
    app = build_ui()
    # Use server_name and server_port if needed; Gradio will pick defaults
    app.launch(server_name="0.0.0.0", server_port=7860, share=False)
