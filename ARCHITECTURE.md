# 🧩 Architecture — Agent QA & Test Automation (Version Expert)

Ce document décrit l’architecture complète du projet **Agent QA & Test Automation**, un système intelligent capable d’analyser un codebase, générer des tests, les exécuter dans un environnement isolé, analyser les erreurs et proposer des corrections.

---

# 🏛️ 1. Vue d’ensemble (High‑Level Architecture)

┌──────────────────────────────┐
│          Gradio UI            │
│  (Dashboard utilisateur)      │
└───────────────┬──────────────┘
│
▼
┌────────────────────────────┐
│        FastAPI Backend      │
│  (Orchestrateur principal)  │
└──────────────┬─────────────┘
│
┌──────────────────────────┼──────────────────────────┐
▼                          ▼                          ▼
┌────────────────┐       ┌────────────────────┐      ┌────────────────────┐
│ Reader Agent    │       │ Test Generator     │      │ Error Analyst       │
│ (Analyse code)  │       │ Agent (LLM + RAG)  │      │ Agent (LLM + Logs)  │
└───────┬─────────┘       └──────────┬─────────┘      └──────────┬─────────┘
│                              │                           │
▼                              ▼                           ▼
┌────────────────┐       ┌────────────────────┐      ┌────────────────────┐
│ Vector Store   │       │ Model Server (LLM) │      │ Sandbox Executor    │
│ (ChromaDB)     │       │ (Ollama / TGI)     │      │ (Docker isolé)      │
└────────────────┘       └────────────────────┘      └────────────────────┘


---

# 🧠 2. Description détaillée des composants

## 🎨 A. Gradio UI
Interface utilisateur moderne permettant :
- Upload du repo (zip)
- Visualisation de la structure du code
- Aperçu des tests générés
- Logs en temps réel
- Rapport qualité final

**Rôle :** offrir une interface simple, efficace et professionnelle.

---

## ⚙️ B. FastAPI Backend
Responsable de :
- L’orchestration des agents
- La gestion des workflows :
  - Analyse → Génération → Exécution → Analyse → Rapport
- La communication avec :
  - Vector Store
  - Model Server
  - Sandbox Executor

**Rôle :** cœur opérationnel du système.

---

## 🔍 C. Reader Agent
Fonctionnalités :
- Analyse AST Python
- Extraction des classes, fonctions, endpoints, dépendances
- Résumés automatiques
- Indexation dans ChromaDB

**Rôle :** comprendre le code comme un ingénieur.

---

## 🧪 D. Test Generator Agent
Fonctionnalités :
- Génération de tests :
  - unitaires
  - intégration
  - API
  - paramétrés
  - mocks
- Utilisation d’un LLM spécialisé code :
  - Qwen2.5‑Coder
  - StarCoder2
  - CodeLlama
- RAG avec :
  - documentation Python
  - documentation pytest
  - documentation FastAPI
  - patterns de tests

**Rôle :** produire des tests pertinents et robustes.

---

## 🧫 E. Sandbox Executor
Fonctionnalités :
- Exécution des tests dans un conteneur isolé
- Capture :
  - logs
  - stacktraces
  - coverage
  - temps d’exécution
- Sécurité :
  - CPU limit
  - RAM limit
  - Timeout

**Rôle :** exécuter les tests sans risque pour l’hôte.

---

## 🧠 F. Error Analyst Agent
Fonctionnalités :
- Analyse des logs
- Détection de la cause racine
- Propositions de corrections
- Génération de patchs (diff)
- Suggestions de refactoring

**Rôle :** agir comme un ingénieur QA senior.

---

## 📚 G. Vector Store (ChromaDB)
Contient :
- embeddings du code
- documentation technique
- patterns de tests
- best practices

**Rôle :** mémoire technique du système.

---

## 🤖 H. Model Server (LLM)
Serveur de modèles :
- Ollama
- HuggingFace TGI

Modèles recommandés :
- Qwen2.5‑Coder
- StarCoder2
- CodeLlama

**Rôle :** moteur d’intelligence du système.

---

# 🐳 3. Architecture de déploiement (Docker Expert)

docker-compose.yml
│
├── api                (FastAPI)
├── frontend           (Gradio)
├── vectorstore        (ChromaDB)
├── model-server       (Ollama / TGI)
└── sandbox            (Docker isolé)

Reverse proxy Nginx :
- HTTPS (Let’s Encrypt)
- Compression
- CORS
- Rate limiting

---

# 🧭 4. Diagramme de flux (Workflow complet)

[1] User upload repo
│
▼
[2] Reader Agent analyse le code
│
▼
[3] Indexation RAG
│
▼
[4] Test Generator crée les tests
│
▼
[5] Sandbox Executor exécute les tests
│
▼
[6] Error Analyst analyse les erreurs
│
▼
[7] Rapport final + suggestions + patchs



---

# 🧨 5. Fonctionnalités premium (Version Expert)

- Auto‑refactoring intelligent  
- Coverage‑aware test generation  
- PR Reviewer Agent (GitHub)  
- Mode TDD assisté  
- Rapport qualité PDF  
- Analyse de complexité cyclomatique  
- Détection de duplication de code  

---

# 📌 Conclusion

Cette architecture fournit un système complet, modulaire, scalable et professionnel, combinant :

- Agents spécialisés  
- RAG avancé  
- LLM orientés code  
- Exécution sécurisée  
- Interface Gradio moderne  
- Déploiement Docker expert  

Parfait pour un portfolio d’ingénieur IA / MLOps / DevOps.
