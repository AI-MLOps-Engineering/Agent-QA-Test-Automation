![CI](https://github.com/AI-MLOps-Engineering/Agent-QA-Test-Automation/actions/workflows/ci.yml/badge.svg)


# 🤖 Agent QA & Test Automation  
Plateforme d’analyse automatisée de dépôts GitHub, combinant LLM, vectorisation, extraction de connaissances et interface utilisateur Gradio.

---

## 🏗️ Architecture du projet

Le projet est structuré en **4 services principaux**, orchestrés via **Docker Compose** :

| Service        | Description |
|----------------|-------------|
| **API**        | Backend FastAPI orchestrant l’analyse, la vectorisation, les appels au modèle et la génération de rapports. |
| **Model**      | Service LLM local (ou wrapper) exposant une API HTTP pour l’inférence. |
| **Vectorstore**| Base vectorielle (ChromaDB) pour stocker et rechercher les embeddings. |
| **Frontend**   | Interface utilisateur Gradio permettant d’uploader un repo ZIP et de lancer l’analyse. |

Chaque service est isolé dans son propre conteneur et communique via un réseau interne Docker.

Une pipeline en script shell, **ci/e2e-integration.ps1** permet d'enchainer les 4 services en une fois.
Pareillement, une pipeline CI/CD **.github/workflows/ci.yml** via Github Actions permet l'enchainement de ces 4 services.

---

## 🛠️ Stack technique

| Composant | Technologie |
|---|---|
| API serving | FastAPI |
| Containerisation | Docker |
| CI/CD | GitHub Actions |
| Web | Gradio |


## 📁 Structure du projet

```texte

├── docker-compose.yml
├── src/
│   ├── api/              # Backend FastAPI
│   ├── model/            # Service modèle (LLM)
│   ├── vectorstore/      # Service ChromaDB
│   └── frontend/         # Interface Gradio
│       ├── gradio_app.py
│       ├── requirements.txt
│       └── Dockerfile
└── README.md
```

---

## 🐳 Lancement du projet

### 1. Prérequis
- Docker  
- Docker Compose  
- (Optionnel) Python 3.11 si tu veux exécuter les services localement

### 2. Démarrer tous les services

```bash
docker compose up -d --build
```

### 3. Vérifier l’état des conteneurs

```bash
docker compose ps
```

On doi voir :
- api → healthy
- frontend → healthy
- model → starting/healthy selon le temps de chargement
- vectorstore → starting/healthy

### 4. Accéder à l’interface Gradio

👉 http://127.0.0.1:7860/

### 5. Accéder à la documentation API

👉 http://127.0.0.1:8000/docs (127.0.0.1 in Bing)

---

## 🧠 Fonctionnement général

- 1. L’utilisateur upload un fichier ZIP contenant un dépôt GitHub.

- 2. Le frontend envoie le fichier à l’API.

- 3. L’API :

    - extrait le ZIP,

    - vectorise les fichiers pertinents,

    - interroge le modèle LLM,

    - génère un rapport d’analyse.

- 4. Le frontend affiche le résultat.

---

##  🔧 Développement

### Redémarrer un service spécifique
```bash
docker compose restart frontend
docker compose restart api
```

### Rebuild uniquement le frontend
bash
docker compose build frontend

### Arrêter tous les services
```bash
docker compose down
```

### Arrêter + supprimer volumes (reset complet)
```bash
docker compose down --volumes --remove-orphans
```

---

## 🧪 Tests

Les tests unitaires et d’intégration (si présents) se trouvent dans src/api/tests.

Exécution locale :

```bash
pytest -q
```

---

## 🛠️ Débogage

### Logs d’un service
```bash
docker compose logs -f frontend
docker compose logs -f api
```

### Tester l’API depuis le conteneur frontend
```bash
docker compose exec frontend curl -v http://api:8000/health
```

### Vérifier la connectivité interne
```bash
docker compose exec frontend ping api
```

---

## 📌 Points importants

- Le frontend Gradio doit être lancé avec :

```python
demo.launch(server_name="0.0.0.0", server_port=7860)
```

- Le healthcheck du frontend utilise curl → curl doit être installé dans l’image.

- Le montage du volume ./src/frontend:/app peut écraser les assets → à activer uniquement en mode développement.

- L’API doit exposer les endpoints attendus par le frontend (upload, analyse, etc.).
