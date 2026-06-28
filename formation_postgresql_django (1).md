# Formation : De Django ORM à PostgreSQL

## Introduction

Ce document explique comment traduire un modèle Django (`Evenement` et `Inscription`) en base de données PostgreSQL réelle. Deux chemins sont possibles : écrire le SQL manuellement (pour comprendre) ou laisser Django gérer les migrations (pour la production).

---

## Partie 1 — Schéma de la base de données

Le modèle Django définit **3 tables** :

| Table Django | Table PostgreSQL | Rôle |
|---|---|---|
| `User` (Django auth) | `auth_user` | Les organisateurs (comptes) |
| `Evenement` | `evenements_evenement` | Les événements créés |
| `Inscription` | `evenements_inscription` | Les inscriptions aux événements |

**Relations :**
- Un `User` peut organiser plusieurs `Evenement` (1 → N)
- Un `Evenement` peut avoir plusieurs `Inscription` (1 → N)

---

## Partie 2 — Créer la base de données PostgreSQL

### Étape 1 : Créer la base et l'utilisateur

```sql
-- En tant que superuser postgres
CREATE DATABASE gestion_evenements;
CREATE USER mon_app_user WITH PASSWORD 'motdepasse_securise';
GRANT ALL PRIVILEGES ON DATABASE gestion_evenements TO mon_app_user;
```

### Étape 2 : Créer la table `evenements_evenement`

```sql
CREATE TABLE evenements_evenement (
    id              SERIAL PRIMARY KEY,
    organisateur_id INTEGER NOT NULL,
    titre           VARCHAR(200) NOT NULL,
    description     TEXT NOT NULL DEFAULT '',
    date_debut      TIMESTAMPTZ NOT NULL,
    date_fin        TIMESTAMPTZ NOT NULL,
    lieu            VARCHAR(255) NOT NULL,
    places_totales  INTEGER NOT NULL CHECK (places_totales >= 0),
    date_creation   TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    -- Clé étrangère vers l'utilisateur Django
    CONSTRAINT fk_organisateur
        FOREIGN KEY (organisateur_id)
        REFERENCES auth_user(id)
        ON DELETE CASCADE,

    -- Contrainte métier : la fin doit être >= au début
    CONSTRAINT date_fin_apres_date_debut
        CHECK (date_fin >= date_debut)
);
```

### Étape 3 : Créer la table `evenements_inscription`

```sql
CREATE TABLE evenements_inscription (
    id                   SERIAL PRIMARY KEY,
    evenement_id         INTEGER NOT NULL,
    nom                  VARCHAR(150) NOT NULL,
    prenoms              VARCHAR(200) NOT NULL,
    telephone1           VARCHAR(30) NOT NULL,
    ville                VARCHAR(150) NOT NULL,
    email                VARCHAR(254) NOT NULL,
    statut               VARCHAR(12) NOT NULL DEFAULT 'EN_ATTENTE',
    token_confirmation   VARCHAR(64) NOT NULL UNIQUE,
    date_inscription     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    date_expiration      TIMESTAMPTZ NOT NULL,
    date_confirmation    TIMESTAMPTZ,  -- NULL autorisé (pas encore confirmée)

    -- Clé étrangère vers l'événement
    CONSTRAINT fk_evenement
        FOREIGN KEY (evenement_id)
        REFERENCES evenements_evenement(id)
        ON DELETE CASCADE,

    -- Valeurs autorisées pour le statut
    CONSTRAINT statut_valide
        CHECK (statut IN ('EN_ATTENTE', 'CONFIRMEE', 'EXPIREE'))
);
```

### Étape 4 : Ajouter l'index partiel (contrainte conditionnelle)

Le modèle Django utilise un `UniqueConstraint` conditionnel — un même email ne peut pas avoir
deux inscriptions **actives** (EN_ATTENTE ou CONFIRMEE) pour le même événement.
En PostgreSQL, cela se traduit par un **index unique partiel** :

```sql
-- Un email ne peut être inscrit qu'une seule fois par événement
-- tant que son statut est EN_ATTENTE ou CONFIRMEE.
-- Les inscriptions EXPIREES ne bloquent pas une nouvelle tentative.
CREATE UNIQUE INDEX unique_email_actif_par_evenement
    ON evenements_inscription (evenement_id, email)
    WHERE statut IN ('EN_ATTENTE', 'CONFIRMEE');
```

---

## Partie 3 — Concepts clés expliqués

### Correspondance Django ORM → PostgreSQL

| Concept Django | Équivalent PostgreSQL | Explication |
|---|---|---|
| `SERIAL PRIMARY KEY` | `id SERIAL PRIMARY KEY` | Entier auto-incrémenté |
| `auto_now_add=True` | `DEFAULT NOW()` | Horodatage automatique à l'insertion |
| `on_delete=CASCADE` | `ON DELETE CASCADE` | Suppression en cascade |
| `CheckConstraint` | `CHECK (...)` | Règle métier validée par la DB |
| `UniqueConstraint` conditionnel | `CREATE UNIQUE INDEX ... WHERE` | Index partiel PostgreSQL |
| `choices=Statut.choices` | `CHECK (statut IN (...))` | Enum simulée par une contrainte |
| `blank=True` | `DEFAULT ''` ou pas de `NOT NULL` | Champ optionnel |
| `null=True, blank=True` | colonne sans `NOT NULL` | Colonne nullable |

### Pourquoi `TIMESTAMPTZ` et pas `TIMESTAMP` ?

`TIMESTAMPTZ` (timestamp with time zone) stocke l'heure en UTC et la convertit automatiquement
selon le fuseau horaire de la session. C'est ce que Django utilise par défaut quand
`USE_TZ = True` dans `settings.py`. Toujours préférer `TIMESTAMPTZ`.

### Pourquoi `ON DELETE CASCADE` ?

Dans le modèle Django :
```python
organisateur = models.ForeignKey(..., on_delete=models.CASCADE)
```
Si un organisateur est supprimé, tous ses événements sont supprimés automatiquement.
Si un événement est supprimé, toutes ses inscriptions le sont aussi.

---

## Partie 4 — Configurer Django pour utiliser PostgreSQL

### settings.py

```python
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.postgresql',
        'NAME': 'gestion_evenements',
        'USER': 'mon_app_user',
        'PASSWORD': 'motdepasse_securise',
        'HOST': 'localhost',
        'PORT': '5432',
    }
}

# Toujours activer le support des fuseaux horaires
USE_TZ = True
```

### Installer le driver PostgreSQL

```bash
pip install psycopg2-binary
```

### Laisser Django créer les tables automatiquement

```bash
# Générer les fichiers de migration (une seule fois par modification du modèle)
python manage.py makemigrations

# Appliquer les migrations à la base de données
python manage.py migrate
```

---

## Partie 5 — Vérifier que tout est en place

### Dans psql

```sql
-- Se connecter à la base
\c gestion_evenements

-- Lister toutes les tables
\dt

-- Voir la structure d'une table
\d evenements_evenement
\d evenements_inscription

-- Vérifier les contraintes CHECK
SELECT conname, contype, pg_get_constraintdef(oid) AS definition
FROM pg_constraint
WHERE conrelid = 'evenements_inscription'::regclass;

-- Vérifier les index (dont l'index partiel)
SELECT indexname, indexdef
FROM pg_indexes
WHERE tablename = 'evenements_inscription';
```

### Résultat attendu pour les index

```
indexname                          | indexdef
-----------------------------------+---------------------------------------------------------
evenements_inscription_pkey        | CREATE UNIQUE INDEX ... ON id
evenements_inscription_token_...   | CREATE UNIQUE INDEX ... ON token_confirmation
unique_email_actif_par_evenement   | CREATE UNIQUE INDEX ... WHERE statut IN (...)
```

---

## Partie 6 — Requêtes SQL équivalentes aux propriétés Django

Le modèle Django définit des propriétés calculées (`@property`). Voici leurs équivalents SQL :

### `nombre_inscrits`

```python
# Django
@property
def nombre_inscrits(self):
    return self.inscriptions.filter(statut=Inscription.Statut.CONFIRMEE).count()
```

```sql
-- SQL
SELECT COUNT(*) 
FROM evenements_inscription 
WHERE evenement_id = 1 
  AND statut = 'CONFIRMEE';
```

### `places_restantes`

```sql
SELECT 
    e.places_totales - COUNT(i.id) AS places_restantes
FROM evenements_evenement e
LEFT JOIN evenements_inscription i 
    ON i.evenement_id = e.id AND i.statut = 'CONFIRMEE'
WHERE e.id = 1
GROUP BY e.places_totales;
```

### `est_complet`

```sql
SELECT 
    CASE WHEN COUNT(i.id) >= e.places_totales THEN TRUE ELSE FALSE END AS est_complet
FROM evenements_evenement e
LEFT JOIN evenements_inscription i 
    ON i.evenement_id = e.id AND i.statut = 'CONFIRMEE'
WHERE e.id = 1
GROUP BY e.places_totales;
```

### Événements publics (`publics()` — filtre sur `is_active`)

```sql
-- Équivalent de EvenementQuerySet.publics()
SELECT e.*
FROM evenements_evenement e
JOIN auth_user u ON u.id = e.organisateur_id
WHERE u.is_active = TRUE
ORDER BY e.date_debut;
```

---

## Résumé

```
Django Model  →  makemigrations  →  migrate  →  PostgreSQL
     ↓                                               ↓
models.py                                     Tables + Contraintes
CheckConstraint                               CHECK (...)
UniqueConstraint(condition=...)               CREATE UNIQUE INDEX ... WHERE
on_delete=CASCADE                             ON DELETE CASCADE
auto_now_add=True                             DEFAULT NOW()
```

En **développement** : utilisez `manage.py migrate` — Django s'occupe de tout.  
En **production** : même approche, mais révisez les migrations avant de les appliquer.  
Le SQL manuel présenté ici sert à comprendre ce que Django génère sous le capot.

---

## Partie 7 — MCD (Merise) et diagramme de classes UML

### MCD — Modèle Conceptuel des Données (Merise)

Le MCD représente les entités métier et leurs associations, indépendamment de toute implémentation technique.

```
┌─────────────────┐          ┌──────────────────────┐          ┌──────────────────────────┐
│  UTILISATEUR    │          │     EVENEMENT         │          │      INSCRIPTION          │
│─────────────────│          │──────────────────────│          │──────────────────────────│
│ #id_utilisateur │          │ #id_evenement         │          │ #id_inscription           │
│  username       │          │  titre                │          │  nom                      │
│  email          │          │  description          │          │  prenoms                  │
│  password       │          │  date_debut           │          │  telephone1               │
│  is_active      │          │  date_fin             │          │  ville                    │
│  date_joined    │          │  lieu                 │          │  email                    │
└────────┬────────┘          │  places_totales       │          │  statut                   │
         │                   │  date_creation        │          │  token_confirmation        │
         │                   │  *organisateur_id     │          │  date_inscription          │
         │                   └──────────┬────────────┘          │  date_expiration           │
         │                              │                        │  date_confirmation         │
       1,1                            1,1                        └────────────────────────────┘
         │                              │                                     ▲
    (organise)                      (reçoit)                                0,N
         │                              │                                     │
       0,N                            0,N ────────────────────────────────────┘
```

**Lecture des cardinalités :**
- Un `UTILISATEUR` organise **0 ou N** événements
- Un `EVENEMENT` est organisé par **exactement 1** utilisateur
- Un `EVENEMENT` reçoit **0 ou N** inscriptions
- Une `INSCRIPTION` concerne **exactement 1** événement

**Légende :**
- `#` = identifiant (clé primaire)
- `*` = clé étrangère
- `1,1` = exactement un
- `0,N` = zéro ou plusieurs

---

### Diagramme de classes UML

Le diagramme UML ajoute les **types de données**, les **méthodes**, et les **relations orientées objet**.

```
┌──────────────────────────────┐
│           User               │
│──────────────────────────────│
│ +id : int                    │
│ +username : str              │
│ +email : str                 │
│ +password : str              │
│ +is_active : bool            │
│ +date_joined : datetime      │
└──────────────┬───────────────┘
               │ 1
               │ organise
               │ 0..*
┌──────────────▼───────────────┐
│          Evenement           │
│──────────────────────────────│
│ +id : int                    │
│ +titre : str                 │
│ +description : str           │
│ +date_debut : datetime       │
│ +date_fin : datetime         │
│ +lieu : str                  │
│ +places_totales : int        │
│ +date_creation : datetime    │
│──────────────────────────────│
│ +nombre_inscrits() : int     │  ← @property
│ +places_restantes() : int    │  ← @property
│ +est_complet() : bool        │  ← @property
│ +duree_en_jours() : int      │  ← @property
│ +sur_un_seul_jour() : bool   │  ← @property
└──────────────┬───────────────┘
               │ 1
               │ reçoit
               │ 0..*
┌──────────────▼───────────────┐     ┌──────────────────┐
│         Inscription          │     │     <<enum>>     │
│──────────────────────────────│     │      Statut      │
│ +id : int                    │     │──────────────────│
│ +nom : str                   │     │  EN_ATTENTE      │
│ +prenoms : str               │─────│  CONFIRMEE       │
│ +telephone1 : str            │ a un│  EXPIREE         │
│ +ville : str                 │     └──────────────────┘
│ +email : str                 │
│ +statut : Statut             │
│ +token_confirmation : str    │
│ +date_inscription : datetime │
│ +date_expiration : datetime  │
│ +date_confirmation : datetime│
│──────────────────────────────│
│ +nom_complet() : str         │  ← @property
│ +est_expiree() : bool        │  ← @property
│ +confirmer() : bool          │  ← méthode métier
│ +clean()                     │  ← validation
└──────────────────────────────┘
```

**Différences MCD vs UML :**

| Aspect | MCD (Merise) | UML Classe |
|---|---|---|
| Types de données | Non précisés | Précisés (`int`, `str`, `bool`...) |
| Méthodes | Absentes | Présentes (`confirmer()`, `est_complet()`...) |
| Enum | Non représentée | Classe stéréotypée `<<enum>>` |
| But | Modélisation métier | Conception technique |
| Utilisateurs | Analyste, client | Développeur |
