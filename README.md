# Mes Événements — plateforme multi-organisateurs (Django)

Plateforme où plusieurs organisateurs créent librement leur compte et publient
leurs événements. Les visiteurs s'inscrivent via un formulaire (nom, prénoms,
téléphone, ville, email), confirment leur inscription par email (double
opt-in), et sont alors comptabilisés dans les places disponibles et ajoutés
au fichier Excel des inscrits de l'événement.

## Démarrage rapide

```bash
# 1. Se placer dans le dossier du projet
cd projet_events

# 2. Créer un environnement virtuel (recommandé)
python -m venv venv
source venv/bin/activate          # sur Windows : venv\Scripts\activate

# 3. Installer les dépendances (Django + openpyxl pour l'export Excel)
pip install -r requirements.txt

# 4. Appliquer les migrations (crée la base SQLite)
python manage.py migrate

# 5. Créer un compte super-administrateur (accès à /admin/, optionnel)
python manage.py createsuperuser

# 6. Lancer le serveur de développement
python manage.py runserver
```

Puis ouvrez :
- **Site public** : http://127.0.0.1:8000/
- **Devenir organisateur** : http://127.0.0.1:8000/organisateur/inscription/
- **Administration globale** : http://127.0.0.1:8000/admin/

## Parcours visiteur (inscription à un événement)

1. Le visiteur consulte la liste des événements et choisit le sien.
2. Il remplit le formulaire : nom, prénoms, téléphone, ville, email.
3. Une inscription est créée avec le statut `EN_ATTENTE` (ne décompte
   **aucune place**) et un email contenant un lien de confirmation est envoyé.
4. Le visiteur clique sur le lien dans les **48 heures**.
5. L'inscription passe à `CONFIRMEE`, la place est décomptée, et le fichier
   Excel de l'événement (un fichier par événement, dans `media/inscrits/`)
   est automatiquement régénéré à partir de la base de données.

Si le lien n'est pas cliqué dans les 48h, l'inscription doit être marquée
comme expirée — voir la commande `expirer_inscriptions` ci-dessous.

## Parcours organisateur

1. Inscription libre sur `/organisateur/inscription/` (nom d'utilisateur,
   email, mot de passe).
2. **Le compte est créé inactif** : il ne peut pas encore se connecter.
   Une page lui indique de régler les frais d'accès directement (en
   personne, hors application).
3. L'organisateur paie l'administrateur du site (toi) en direct.
4. Toi tu actives le compte depuis `/admin/` (Utilisateurs → sélectionner
   le compte → action "✅ Activer les comptes sélectionnés").
5. L'organisateur peut alors se connecter sur `/organisateur/connexion/`.
6. Dans `/organisateur/dashboard/` : création, modification, suppression de
   ses propres événements uniquement.
7. Pour chaque événement : consultation des inscrits (confirmés / en
   attente) et téléchargement du fichier Excel des inscrits confirmés.

**Paiement** : il n'y a aucune intégration de paiement en ligne dans
l'application — le règlement se fait entièrement hors plateforme entre toi
et chaque organisateur. `is_active` est le seul levier technique liant
"paiement reçu" à "accès débloqué", et il est entièrement manuel.

**Désactivation a posteriori** : la même action admin sert aussi à bloquer
un compte abusif après coup (action "🚫 Désactiver"). Ses événements
disparaissent alors immédiatement du site public et toute session déjà
ouverte est coupée à la requête suivante.

**Isolation entre organisateurs** : chaque organisateur ne voit et ne peut
modifier que ses propres événements. Toute tentative d'accéder à l'événement
d'un autre organisateur (même en modifiant l'URL) renvoie une erreur 404,
sans révéler que l'événement existe. Voir les tests dans
`MultiTenantIsolationTests` (`events/tests.py`).

## Expiration des inscriptions en attente (tâche planifiée)

Les inscriptions `EN_ATTENTE` depuis plus de 48h doivent être marquées
`EXPIREE` régulièrement, sinon une personne n'ayant jamais cliqué sur son
lien ne pourrait pas retenter une inscription avec le même email. Cela se
fait via une commande de gestion Django, à exécuter périodiquement (toutes
les heures par exemple) :

```bash
python manage.py expirer_inscriptions
```

En production, planifiez cette commande avec une tâche cron (Linux) ou
l'équivalent fourni par votre hébergeur (ex : "Scheduled Tasks" sur
PythonAnywhere, "Cron Jobs" sur Render).

## Lancer les tests automatisés

```bash
python manage.py test
```

Les tests couvrent notamment :
- le calcul des places restantes (ne compte que les inscriptions confirmées),
- la création d'une inscription en attente et l'envoi de l'email avec le lien,
- la confirmation réussie via le lien (passage à CONFIRMEE),
- l'échec de confirmation si le lien est expiré ou si l'événement est devenu
  complet entre-temps,
- le refus d'une seconde inscription active avec le même email sur le même
  événement, et la possibité de retenter après expiration,
- **l'isolation multi-tenant** : un organisateur ne peut jamais accéder aux
  événements ou aux inscrits d'un autre organisateur,
- la commande `expirer_inscriptions`.

## Fichiers Excel des inscrits

Chaque événement a son propre fichier Excel, généré dans
`media/inscrits/inscrits_<id>_<titre>.xlsx`, contenant les colonnes :
Nom, Prénoms, Téléphone, Ville, Email, Date de confirmation.

Le fichier est **entièrement régénéré** à partir de la base de données à
chaque nouvelle confirmation (la base de données reste la source de
vérité) — il n'y a donc jamais de désynchronisation possible entre la base
et le fichier Excel téléchargé par l'organisateur.

## Emails en développement

Par défaut, les emails ne sont pas réellement envoyés : ils s'affichent dans
la console où tourne `runserver` (voir `EMAIL_BACKEND` dans `settings.py`).
Le lien de confirmation s'y trouve donc directement, pratique pour tester
le parcours complet sans configurer de vrai service SMTP.

Pour un envoi réel en production, voir `GUIDE_PRODUCTION.md`.

## Structure du projet

```
projet_events/
├── manage.py
├── requirements.txt
├── .gitignore
├── GUIDE_PRODUCTION.md       # checklist complète de mise en production
├── db.sqlite3                (créé après migrate)
├── media/inscrits/           (fichiers Excel générés, créé automatiquement)
├── projet_events/            # configuration globale
│   ├── settings.py
│   ├── urls.py
│   └── wsgi.py
├── events/                   # application principale
│   ├── models.py             # Evenement, Inscription (statuts + token)
│   ├── views.py               # espace public + espace organisateur
│   ├── forms.py                # InscriptionForm, OrganisateurCreationForm, EvenementForm
│   ├── admin.py                # configuration Django Admin
│   ├── excel_export.py         # génération du fichier Excel par événement
│   ├── urls.py
│   ├── tests.py
│   ├── management/commands/
│   │   └── expirer_inscriptions.py
│   ├── migrations/
│   └── templates/events/       # 13 templates (public + organisateur)
├── templates/
│   └── base.html                # navigation incluant connexion/dashboard
└── static/css/style.css
```

## Prochaines étapes possibles

- Paiement en ligne par événement (PayPal, CinetPay Mobile Money).
- Page de calendrier (vue mensuelle des événements).
- Déploiement (Render, PythonAnywhere...) + passage en PostgreSQL — voir
  `GUIDE_PRODUCTION.md`.
