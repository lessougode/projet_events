

# Guide de mise en production — Mes Événements (Django)

Ce document liste **tout** ce qu'il faut configurer ou changer avant de mettre l'application en ligne, avec les explications, et un comparatif d'hébergeurs gratuits/peu chers à jour (juin 2026).

---

## Sommaire

1. [Vue d'ensemble : dev vs prod](#1-vue-densemble--dev-vs-prod)
2. [🔴 Critique — Sécurité (`settings.py`)](#2--critique--sécurité-settingspy)
3. [🟠 Important — Base de données (PostgreSQL)](#3--important--base-de-données-postgresql)
4. [🟠 Important — Fichiers statiques](#4--important--fichiers-statiques)
5. [🟠 Important — Serveur d'application (Gunicorn)](#5--important--serveur-dapplication-gunicorn)
6. [🟡 Recommandé — HTTPS et cookies sécurisés](#6--recommandé--https-et-cookies-sécurisés)
7. [🟡 Recommandé — Emails en production](#7--recommandé--emails-en-production)
8. [🟡 Recommandé — Logging des erreurs](#8--recommandé--logging-des-erreurs)
9. [Fichier `.env` et variables d'environnement](#9-fichier-env-et-variables-denvironnement)
10. [Comparatif des hébergeurs gratuits/peu chers (2026)](#10-comparatif-des-hébergeurs-gratuitspeu-chers-2026)
11. [Checklist finale avant mise en ligne](#11-checklist-finale-avant-mise-en-ligne)

---

## 1. Vue d'ensemble : dev vs prod

| Aspect | En développement (actuellement) | En production (à faire) |
|---|---|---|
| `DEBUG` | `True` | `False` |
| `SECRET_KEY` | codée en dur dans le fichier | variable d'environnement |
| `ALLOWED_HOSTS` | vide | ton/tes domaine(s) |
| Base de données | SQLite (fichier local) | PostgreSQL |
| Fichiers statiques (CSS) | servis automatiquement | nécessite `collectstatic` + WhiteNoise |
| Serveur | `python manage.py runserver` | Gunicorn (ou équivalent) |
| Emails | affichés dans la console | vrai service SMTP |
| HTTPS | aucun (http simple) | obligatoire |

Le principe général : **rien ne doit être codé en dur**. Toutes les valeurs sensibles ou qui changent entre environnements passent par des **variables d'environnement**.

---

## 2. 🔴 Critique — Sécurité (`settings.py`)

### 2.1 SECRET_KEY

**Le problème :** `SECRET_KEY` sert à signer les sessions, les cookies, les tokens CSRF. Actuellement elle est écrite en clair dans `settings.py` avec une valeur prévisible ("CHANGEZ-MOI"). N'importe qui ayant accès au code (ou au dépôt Git si publié) pourrait forger des sessions ou casser la sécurité du site.

**La solution :**

1. Générer une vraie clé secrète aléatoire :
```bash
python -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"
```

2. Modifier `settings.py` pour la lire depuis une variable d'environnement :
```python
import os
SECRET_KEY = os.environ.get("SECRET_KEY")
```

3. Définir cette variable **uniquement** sur le serveur de prod (jamais dans le code Git).

**Important :** ne mets jamais cette clé dans un fichier versionné sur GitHub.

---

### 2.2 DEBUG

**Le problème :** avec `DEBUG = True`, si une erreur survient, Django affiche une page détaillée avec : le code source de la vue en cause, les valeurs de toutes tes variables d'environnement, la structure de ta base de données, les chemins de fichiers sur ton serveur. C'est une fuite d'information critique si un visiteur tombe sur une erreur.

**La solution :**
```python
DEBUG = os.environ.get("DEBUG", "False") == "True"
```
Ainsi : pas de variable définie → `False` par défaut (sûr). En dev local, tu définis `DEBUG=True` dans ton environnement.

---

### 2.3 ALLOWED_HOSTS

**Le problème :** avec `ALLOWED_HOSTS = []`, Django refuse déjà tout en prod — mais il faut explicitement autoriser ton (tes) domaine(s), sinon le site renvoie une erreur 400 "Bad Request" à tous les visiteurs.

**La solution :**
```python
ALLOWED_HOSTS = os.environ.get("ALLOWED_HOSTS", "").split(",")
# Exemple de valeur de la variable d'environnement :
# ALLOWED_HOSTS=monsite.onrender.com,www.monsite.com
```

---

## 3. 🟠 Important — Base de données (PostgreSQL)

**Le problème :** SQLite est un simple fichier sur le disque. Il ne gère pas bien les écritures simultanées — si deux personnes s'inscrivent à un événement au même moment, l'une des deux requêtes peut être bloquée ou échouer. C'est exactement le genre de situation qui arrivera avec un formulaire d'inscription public.

**La solution :** passer à PostgreSQL, qui gère correctement la concurrence. Le modèle est déjà prêt pour ça (le `settings.py` du squelette contient un bloc PostgreSQL commenté).

```python
import dj_database_url  # pip install dj-database-url

DATABASES = {
    "default": dj_database_url.config(
        default=os.environ.get("DATABASE_URL"),
        conn_max_age=600,
    )
}
```

La plupart des hébergeurs (Render, Railway...) génèrent automatiquement une variable `DATABASE_URL` au format :
```
postgresql://utilisateur:motdepasse@hote:5432/nom_base
```
`dj_database_url` sait directement parser cette URL — pas besoin de la décomposer toi-même.

**Étapes une fois la base PostgreSQL créée chez l'hébergeur :**
```bash
python manage.py migrate
python manage.py createsuperuser
```

---

## 4. 🟠 Important — Fichiers statiques

**Le problème :** en développement, `runserver` sert automatiquement ton CSS (`static/css/style.css`). En production, ce mécanisme est désactivé par sécurité/performance — Django n'est pas fait pour servir des fichiers statiques à grande échelle. Sans configuration, ton site sera en ligne mais **sans aucun style** (HTML brut).

**La solution la plus simple : WhiteNoise** (permet à Django de servir les statiques correctement même en prod, sans serveur web séparé).

```bash
pip install whitenoise
```

Dans `settings.py` :
```python
MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",  # juste après SecurityMiddleware
    # ... reste du middleware inchangé
]

STATIC_ROOT = BASE_DIR / "staticfiles"
STORAGES = {
    "staticfiles": {
        "BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage",
    },
}
```

Avant chaque déploiement (ou automatiquement via le script de déploiement de l'hébergeur) :
```bash
python manage.py collectstatic --noinput
```
Cette commande regroupe tous les fichiers CSS/JS du projet dans `staticfiles/`, prêts à être servis.

---

## 5. 🟠 Important — Serveur d'application (Gunicorn)

**Le problème :** `runserver` est explicitement marqué par Django comme non destiné à la production — il est mono-thread, lent, et n'a aucune des protections nécessaires (gestion des timeouts, des pics de charge, etc.).

**La solution : Gunicorn**, un serveur WSGI conçu pour la prod.

```bash
pip install gunicorn
```

Commande de démarrage (généralement demandée par l'hébergeur dans un fichier `Procfile` ou un champ "start command") :
```bash
gunicorn projet_events.wsgi:application
```

Sur la plupart des PaaS (Render, Railway...), cette commande est à renseigner directement dans l'interface de configuration du service, pas besoin de fichier supplémentaire.

---

## 6. 🟡 Recommandé — HTTPS et cookies sécurisés

La plupart des hébergeurs modernes (Render, Railway) fournissent HTTPS automatiquement (certificat Let's Encrypt généré pour toi). Il reste à dire à Django de l'exiger :

```python
if not DEBUG:
    SECURE_SSL_REDIRECT = True
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_HSTS_SECONDS = 31536000
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
```

`SECURE_SSL_REDIRECT` redirige automatiquement tout visiteur arrivant en `http://` vers `https://`. Les options `_COOKIE_SECURE` empêchent que les cookies de session/CSRF transitent en clair.

**Attention :** si ton hébergeur utilise un proxy inverse (cas fréquent sur les PaaS), ajoute aussi :
```python
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
```
Sinon Django pense à tort que la connexion n'est pas sécurisée et boucle sur la redirection.

---

## 7. 🟡 Recommandé — Emails en production

Comme évoqué précédemment, le `EMAIL_BACKEND` actuel (console) n'envoie aucun email réel. En prod, configure un vrai service SMTP :

```python
EMAIL_BACKEND = "django.core.mail.backends.smtp.EmailBackend"
EMAIL_HOST = os.environ.get("EMAIL_HOST")
EMAIL_PORT = 587
EMAIL_USE_TLS = True
EMAIL_HOST_USER = os.environ.get("EMAIL_HOST_USER")
EMAIL_HOST_PASSWORD = os.environ.get("EMAIL_HOST_PASSWORD")
DEFAULT_FROM_EMAIL = os.environ.get("DEFAULT_FROM_EMAIL", "Mes Événements <no-reply@tondomaine.com>")
```

Services avec offre gratuite adaptée à un petit volume (confirmations d'inscription) :
- **Brevo** (ex-Sendinblue) — 300 emails/jour gratuits
- **Mailjet** — 200 emails/jour gratuits
- **SendGrid** — offre gratuite limitée, vérifie les conditions actuelles

Ces services fournissent un host SMTP, un port, un utilisateur et un mot de passe (ou clé API) à renseigner dans les variables d'environnement ci-dessus.

---

## 8. 🟡 Recommandé — Logging des erreurs

**Le problème :** une fois `DEBUG = False`, les erreurs ne s'affichent plus aux visiteurs (c'est voulu, pour la sécurité) — mais toi non plus tu ne les vois plus, sauf à consulter les logs.

**Solution simple :** la plupart des hébergeurs (Render, Railway) affichent déjà les logs du serveur dans leur tableau de bord — souvent suffisant pour un petit projet. Si tu veux être notifié activement des erreurs (recommandé dès que le site a de vrais utilisateurs), un outil comme **Sentry** propose un plan gratuit largement suffisant pour ce projet :

```bash
pip install sentry-sdk
```
```python
import sentry_sdk
if not DEBUG:
    sentry_sdk.init(dsn=os.environ.get("SENTRY_DSN"))
```

Pas obligatoire pour démarrer, mais utile dès que tu ne veux plus dépendre de "quelqu'un qui te signale que ça plante".

---

## 9. Fichier `.env` et variables d'environnement

En local, pour simuler la prod sans tout coder en dur, utilise un fichier `.env` (à ne **jamais** committer sur Git) :

```bash
pip install python-dotenv
```

En haut de `settings.py` :
```python
from dotenv import load_dotenv
load_dotenv()
```

Exemple de fichier `.env` (local, donc avec `DEBUG=True`) :
```
SECRET_KEY=une-cle-generee-aleatoirement
DEBUG=True
ALLOWED_HOSTS=127.0.0.1,localhost
DATABASE_URL=postgresql://localhost/events_db
```

**Ajoute `.env` à ton `.gitignore`** pour ne jamais le pousser sur GitHub :
```
.env
db.sqlite3
__pycache__/
*.pyc
staticfiles/
```

Sur l'hébergeur de prod, ces mêmes variables (`SECRET_KEY`, `DEBUG=False`, `ALLOWED_HOSTS`, `DATABASE_URL`, etc.) se définissent directement dans l'interface web du service (section "Environment Variables" ou équivalent), pas via un fichier `.env`.

---

## 10. Comparatif des hébergeurs gratuits/peu chers (2026)

⚠️ Les offres "gratuites" ont presque toutes des limitations sérieuses depuis que Heroku a supprimé son offre gratuite en 2022. Voici un état honnête, vérifié en juin 2026.

### Render (le plus simple pour démarrer)

- **Web service gratuit** : 512 Mo RAM, se met en veille après 15 minutes sans trafic → le premier visiteur après une pause attend 30-60 secondes (cold start).
- **PostgreSQL gratuit** : 1 Go de stockage, mais la base est **automatiquement supprimée 30 jours après sa création** (avec 14 jours de grâce pour upgrader avant suppression définitive).
- Déploiement direct depuis GitHub, HTTPS automatique, aucune carte bancaire requise pour démarrer.
- **Conclusion** : parfait pour tester/montrer le projet, **pas viable pour garder des données plus de 30 jours** sans passer sur l'offre payante (~7 $/mois pour le web service + ~6 $/mois pour la base).

### Railway

- Crédit gratuit de 5 $ le premier mois, puis seulement 1 $/mois de crédit ensuite.
- 1 $/mois ne suffit pas à faire tourner un service en continu — convient à des tests ponctuels, pas à un site qui doit rester accessible.
- Au-delà : offre "Hobby" à 5 $/mois, généralement suffisante pour ce type de petit projet.

### PythonAnywhere

- Offre historiquement pensée pour Python/Django, débutants.
- 1 application web gratuite, MySQL gratuit inclus — **mais pas de PostgreSQL sur l'offre gratuite**.
- CPU limité (le site reste accessible même au-delà du quota, mais ralentit).
- Le site reste en ligne indéfiniment tant que tu te reconnectes périodiquement (toutes les 3 mois) pour confirmer que le projet est actif.
- **Conclusion** : bonne option si tu acceptes MySQL à la place de PostgreSQL pour rester 100% gratuit. Sinon, leur offre payante démarre à 10 $/mois.

### Hetzner + Appliku (option "vraie offre gratuite la plus longue")

- Hetzner offre 20 € de crédit à l'inscription (carte bancaire requise) ; un petit serveur (2 vCPU, 4 Go RAM) coûte environ 3,79 €/mois → environ **5 mois gratuits réels**.
- Appliku (couche de déploiement façon Heroku par-dessus Hetzner) propose un essai gratuit de 14 jours, puis à partir de ~14 $/mois.
- **Conclusion** : la solution la plus proche d'un vrai hébergement de production gratuit pendant plusieurs mois, mais demande un peu plus de configuration et une carte bancaire dès le départ.

### Tableau récapitulatif

| Hébergeur | PostgreSQL gratuit | Site toujours actif | Carte bancaire requise | Niveau de difficulté |
|---|---|---|---|---|
| **Render** | Oui, 30 jours puis supprimée | Non (veille 15 min) | Non | ⭐ Très simple |
| **Railway** | Oui, mais crédit très limité | Non (crédit insuffisant) | Non | ⭐ Très simple |
| **PythonAnywhere** | Non (MySQL seulement) | Oui | Non | ⭐⭐ Simple |
| **Hetzner + Appliku** | Oui (auto-hébergée) | Oui | Oui | ⭐⭐⭐ Intermédiaire |

### Recommandation pour ce projet

Pour un premier déploiement et pour montrer le projet : **Render**, c'est le plus rapide à mettre en place (15-20 minutes), zéro configuration serveur, et la limite de 30 jours sur la base n'est pas gênante si tu es encore en phase de test/démo.

Le jour où le site doit réellement rester en ligne avec de vraies inscriptions (production réelle, pas démo) : passe sur l'offre payante de Render (~13 $/mois pour le service web + la base) ou sur PythonAnywhere si MySQL te convient (~10 $/mois).

---

## 11. Checklist finale avant mise en ligne

- [ ] `SECRET_KEY` générée aléatoirement, lue depuis une variable d'environnement
- [ ] `DEBUG = False` en production
- [ ] `ALLOWED_HOSTS` contient le(s) bon(s) domaine(s)
- [ ] Base de données passée en PostgreSQL (`dj_database_url` configuré)
- [ ] `python manage.py migrate` exécuté sur la base de prod
- [ ] `python manage.py createsuperuser` exécuté sur la base de prod
- [ ] WhiteNoise installé et configuré, `collectstatic` exécuté
- [ ] Gunicorn configuré comme commande de démarrage
- [ ] `SECURE_SSL_REDIRECT` et cookies sécurisés activés
- [ ] Service SMTP réel configuré (Brevo, Mailjet...) — teste l'envoi d'un email de confirmation réel
- [ ] Fichier `.env` exclu du dépôt Git (`.gitignore` à jour)
- [ ] Test complet du parcours d'inscription en conditions réelles (vraie URL, vrai email reçu)
- [ ] Vérifier que la page d'admin (`/admin/`) n'est accessible qu'avec les identifiants du superuser (pas de compte de test oublié)

---

*Si un point bloque malgré ce guide, reviens avec le message d'erreur exact — je t'aiderai à le résoudre.*


