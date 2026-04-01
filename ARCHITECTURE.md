# 🧩 Architecture — Agent QA & Test Automation (Version Expert)

> Ce document décrit l’architecture complète du projet **Agent QA & Test Automation**, un système intelligent capable d’analyser un codebase, générer des tests, les exécuter dans un environnement isolé, analyser les erreurs et proposer des corrections.  
> Cette architecture fournit un système complet, modulaire, scalable et professionnel, combinant agents spécialisés, RAG avancé, LLM orientés code, exécution sécurisée, interface Gradio moderne et déploiement Docker expert.

---

# 🏛️ 1. Vue d’ensemble (High‑Level Architecture)

Le diagramme ci‑dessous est formaté en bloc de code pour s'afficher correctement sur GitHub. Il représente les composants principaux et leurs connexions.

```text
+----------------------+        +---------------------------+
|      Gradio UI       |  <---- |       Client / User       |
| (Dashboard utilisateur)      |                           |
+----------+-----------+        +---------------------------+
           |
           v
+-------------------------------+
|      FastAPI Backend          |
|  (Orchestrateur principal)    |
+---+-------------------+-------+
    |                   |
    |                   |
    v                   v
+--------+        +-------------+        +------------------+
| Reader | <----> | Vector Store| <----> |  Model Server    |
| Agent  |        |  (ChromaDB) |        |  (Ollama / TGI)  |
+--------+        +-------------+        +------------------+
    |
    v
+----------------+      +--------------------+      +------------------+
| Test Generator | ---> | Sandbox Executor   | ---> | Error Analyst    |
| Agent (LLM+RAG)|      | (Docker isolé)     |      | Agent (LLM+Logs) |
+----------------+      +--------------------+      +------------------+

```


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


Internet
   |
   v
+-----------------+
|     Nginx       |  (reverse proxy, TLS, rate limiting)
+--------+--------+
         |
         v
+-------------------------------+
|        Docker Host / VPS      |
|  (compose network)            |
|  +-------------------------+  |
|  | api        (FastAPI)    |  |
|  +-------------------------+  |
|  | frontend   (Gradio)     |  |
|  +-------------------------+  |
|  | vectorstore (ChromaDB)  |  |
|  +-------------------------+  |
|  | model-server (Ollama/TGI)| |
|  +-------------------------+  |
|  | sandbox    (isolated)   |  |
|  +-------------------------+  |
+-------------------------------+


Reverse proxy Nginx :
- HTTPS (Let’s Encrypt)
- Compression
- CORS
- Rate limiting

---

# 🧭 4. Diagramme de flux (Workflow complet)

[User] uploads repo (zip)
      |
      v
[FastAPI] receives repo -> triggers Reader Agent
      |
      v
[Reader Agent] analyzes code, extracts structure, indexes into Vector Store (ChromaDB)
      |
      v
[Test Generator Agent] (LLM + RAG) generates unit / integration / API tests
      |
      v
[Sandbox Executor] runs tests in isolated Docker container, collects logs & coverage
      |
      v
[Error Analyst Agent] analyzes failures, proposes fixes, generates patch diffs
      |
      v
[FastAPI] aggregates results -> Gradio UI displays: tests, logs, coverage, suggested patches, final report



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
