# My-Social-Networks-API

API REST (FastAPI + SQLAlchemy + SQLite) d'un réseau social : utilisateurs, événements, groupes,
fils de discussion, albums photo, sondages, billetterie, shopping list et covoiturage (bonus).

📘 **Documentation Postman publiée** : https://documenter.getpostman.com/view/59274801/2sBYHbrbNf

## Installation & lancement

```bash
pip install -r requirements.txt
cp .env.example .env                 # puis remplacer JWT_SECRET par une valeur aléatoire
python scripts/generate_cert.py      # certificat HTTPS auto-signé dans certs/
python run.py                        # https://localhost:8443
```

- Swagger : https://localhost:8443/docs — ReDoc : https://localhost:8443/redoc
- La base SQLite `social_networks.db` est créée au démarrage (variable `DATABASE_URL` pour en changer).
  Après une évolution du modèle, supprimer ce fichier pour la recréer.
- Générer un secret JWT : `python -c "import secrets; print(secrets.token_urlsafe(48))"`
- Promouvoir un administrateur : `python scripts/promote_admin.py alice@example.com`

## Tests

```bash
python -m pytest
```

## Sécurité

Mesures reprises du projet Node (`json/`) et adaptées à FastAPI :

| Mesure | Node (`json/`) | Python (ce projet) |
|---|---|---|
| Configuration hors du code | `dotenv`, `.env` ignoré par git | `pydantic-settings` + `.env` ignoré, `.env.example` fourni ([app/config.py](app/config.py)) |
| Démarrage refusé sans secret | `JWT_SECRET is missing` | erreur si `JWT_SECRET` absent ou < 32 caractères |
| Authentification | JWT HS256 + `expiresIn`, `Authorization: Bearer` | JWT HS256 avec `exp`/`iat` obligatoires, algorithme imposé, utilisateur revérifié en base ([app/security.py](app/security.py), [app/deps.py](app/deps.py)) |
| Routes protégées | middleware `authToken` | dépendance `CurrentUser` sur toutes les routes sauf inscription, connexion, achat de billet |
| Rôles / droits | `user` / `admin`, « soi-même ou admin » | rôle `user` / `admin` (non modifiable via l'API) ; soi-même ou admin pour un compte, organisateurs, administrateurs de groupe, auteurs |
| Mots de passe | bcrypt coût 12, `select: false`, politique de complexité | bcrypt coût 12, jamais renvoyé, 8+ caractères avec majuscule, minuscule et chiffre |
| Connexion | message d'erreur générique | message identique que l'email existe ou non, temps de réponse constant (hash factice) |
| En-têtes HTTP | `helmet` | middleware équivalent : CSP, HSTS, `X-Frame-Options`, `nosniff`, `Referrer-Policy`, COOP/CORP… en-tête `Server` supprimé ([app/middleware.py](app/middleware.py)) |
| CORS | liste blanche `CORS_ORIGINS` | `CORSMiddleware` avec `CORS_ORIGINS`, méthodes et en-têtes restreints |
| Limitation de débit | 100 req/h global, 5 connexions / 15 min | global par IP (`RATE_LIMIT_PER_HOUR`, 1000 par défaut) et 5 **échecs** de connexion / 15 min (429 + `Retry-After`) |
| Taille des requêtes | `express.json({ limit: '10kb' })` | 10 Ko max (413), contrôlé sur `Content-Length` et pendant la lecture du corps |
| Gestion des erreurs | `errorHandler` sans fuite de stack | 500 générique journalisé, `IntegrityError` → 409, validations → 422 |
| Recherche | échappement des regex | échappement des jokers SQL `%` et `_` |
| Validation des URL | regex `https?://` | toutes les URL (photos, couvertures, icônes, avatar) en `http(s)://` |
| HTTPS | `https.createServer` + `certs/` | `run.py` lance uvicorn en TLS (`SSL_KEY_PATH`, `SSL_CERT_PATH`), `certs/` ignoré |
| Arrêt propre | fermeture MongoDB sur `SIGINT` | `engine.dispose()` à l'arrêt (lifespan) |

En plus : l'auteur d'une action est toujours l'utilisateur du jeton (impossible d'agir au nom d'un autre),
les événements privés et groupes secrets renvoient 404 aux non-invités, et les données personnelles des
acheteurs de billets ne sont visibles que des organisateurs.

## Documentation Postman

La collection [docs/My-Social-Networks-API.postman_collection.json](docs/My-Social-Networks-API.postman_collection.json)
contient **154 requêtes** réparties en dossiers, chacune avec :
- l'URL du service (`{{baseUrl}}`, par défaut `https://localhost:8443`) et le jeton de l'utilisateur qui agit ;
- l'explication fonctionnelle (docstring de l'endpoint, identique à Swagger) ;
- un exemple réel de la réponse renvoyée (succès et cas d'erreur 401 / 403 / 404 / 409 / 422) ;
- un test Postman sur le code HTTP attendu.

Elle est **exécutable dans l'ordre** (Collection Runner) contre une base vide : le dossier
*Authentification* crée les utilisateurs et enregistre leurs jetons (`token_alice`, `token_bob`…).
Le certificat étant auto-signé, désactiver *SSL certificate verification* dans Postman.
Attention : 5 échecs de connexion en 15 minutes depuis la même IP déclenchent un 429.

Pour la régénérer après une modification de l'API :

```bash
python scripts/build_postman.py
```

Publication : Postman → *Import* du fichier → clic droit sur la collection → *Publish Docs*, puis
reporter l'URL obtenue en haut de ce README.

## Choix de conception

- `PATCH` = mise à jour partielle. Erreurs au format `{"detail": "..."}`.
- Les images (photo de couverture, icône, photos d'album) sont des **URL**.
- Dates ISO 8601, stockées en UTC.

## Règles métier implémentées

| Domaine | Règles |
|---|---|
| Utilisateurs | Email unique (insensible à la casse) ; mot de passe haché, jamais renvoyé ; suppression refusée si seul organisateur d'un événement ou seul admin d'un groupe |
| Événements | Nom, description, début/fin (fin > début), lieu, photo de couverture, visibilité public/privé ; 1+ organisateurs (le créateur d'office) ; participants illimités ; événements privés visibles uniquement par leurs invités |
| Groupes | Nom, description, icône, couverture, type public/privé/secret, autorisation des membres à publier / créer des événements ; 1+ administrateurs (membres d'office) ; groupes secrets invisibles aux non-membres ; fil de discussion créé automatiquement |
| Événements de groupe | Organisateurs membres du groupe (admins si les membres ne peuvent pas créer d'événements) ; invitation de tous les membres en un clic ; partage sur les réseaux sociaux seulement pour un événement public d'un groupe public |
| Fils de discussion | Lié à 1 groupe **ou** 1 événement (contrainte en base) ; messages par les membres / participants (admins seulement si le groupe l'impose) ; commentaires par tout membre / participant |
| Albums photo | Album lié à 1 événement ; photos postées et commentées uniquement par les participants (ou organisateurs) |
| Sondages | Créés par un organisateur ; 1+ questions, 2+ réponses possibles chacune ; un participant choisit exactement 1 réponse par question (re-soumettre remplace) ; questions figées dès la première réponse |
| Billetterie | Uniquement pour un événement public avec billetterie activée ; types de billets (nom, montant, quantité limitée) ; 1 billet par personne (email) et par événement ; billet = type + nom, prénom, adresse complète, date d'achat ; refus si épuisé |
| Shopping list | Si activée ; article (nom, quantité, heure d'arrivée) apporté par un participant ; nom unique par événement |
| Covoiturage (bonus) | Si activé ; trajet (lieu et heure de départ, prix, places, écart maximum) proposé par un participant ; réservation de places dans la limite disponible |

## Endpoints

Toutes les routes exigent `Authorization: Bearer <token>`, sauf `POST /users`, `POST /auth/login`
et `POST /ticket-types/{id}/tickets`.

### Authentification
| Méthode | Route | Description |
|---|---|---|
| POST | `/auth/login` | Obtenir un jeton JWT (email + mot de passe) |
| GET | `/auth/me` | Profil de l'utilisateur connecté |

### Utilisateurs
| Méthode | Route | Description |
|---|---|---|
| POST | `/users` | Inscription (publique) |
| GET | `/users?q=` | Lister / rechercher |
| GET / PATCH / DELETE | `/users/{id}` | Détail / modifier / supprimer |
| GET | `/users/{id}/events?role=all\|organizer\|participant` | Événements de l'utilisateur |
| GET | `/users/{id}/groups` | Groupes de l'utilisateur |

### Groupes
| Méthode | Route | Description |
|---|---|---|
| POST | `/groups` | Créer |
| GET | `/groups?q=&type=` | Lister / rechercher |
| GET / PATCH / DELETE | `/groups/{id}` | Détail / modifier / supprimer |
| POST / DELETE | `/groups/{id}/members/{user_id}` | Ajouter / retirer un membre |
| POST / DELETE | `/groups/{id}/admins/{user_id}` | Nommer / retirer un administrateur |
| GET | `/groups/{id}/events` | Événements du groupe |

### Événements
| Méthode | Route | Description |
|---|---|---|
| POST | `/events` | Créer (étape 1, éventuellement dans un groupe) |
| GET | `/events?q=&visibility=&location=&starts_after=&starts_before=&organizer_id=&participant_id=&group_id=` | Rechercher |
| GET / PATCH / DELETE | `/events/{id}` | Détail / modifier / supprimer |
| POST / DELETE | `/events/{id}/organizers/{user_id}` | Ajouter / retirer un organisateur |
| POST / DELETE | `/events/{id}/participants/{user_id}` | Ajouter / retirer un participant |
| POST | `/events/{id}/invite-group-members` | Inviter tous les membres du groupe |
| GET | `/events/{id}/share` | Liens de partage (Facebook, X, LinkedIn, WhatsApp, email) |
| GET | `/events/{id}/stats` | Statistiques de l'événement |

### Fils de discussion
| Méthode | Route | Description |
|---|---|---|
| POST | `/threads` | Créer (`group_id` **ou** `event_id`) |
| GET | `/threads?group_id=&event_id=` | Lister |
| GET / PATCH / DELETE | `/threads/{id}` | Détail / renommer / supprimer |
| POST / GET | `/threads/{id}/messages` | Publier / lister les messages |
| GET / PATCH / DELETE | `/messages/{id}` | Message |
| POST / GET | `/messages/{id}/comments` | Commenter / lister |
| PATCH / DELETE | `/message-comments/{id}` | Commentaire |

### Albums photo
| Méthode | Route | Description |
|---|---|---|
| POST / GET | `/events/{id}/albums` | Créer / lister |
| GET / PATCH / DELETE | `/albums/{id}` | Album |
| POST / GET | `/albums/{id}/photos` | Poster / lister les photos |
| GET / PATCH / DELETE | `/photos/{id}` | Photo |
| POST / GET | `/photos/{id}/comments` | Commenter / lister |
| PATCH / DELETE | `/photo-comments/{id}` | Commentaire |

### Sondages
| Méthode | Route | Description |
|---|---|---|
| POST / GET | `/events/{id}/polls` | Créer / lister |
| GET / PATCH / DELETE | `/polls/{id}` | Sondage |
| PUT | `/polls/{id}/responses` | Répondre (ou modifier sa réponse) |
| GET | `/polls/{id}/responses?user_id=` | Réponses par participant |
| DELETE | `/polls/{id}/responses/{user_id}` | Supprimer une réponse |
| GET | `/polls/{id}/results` | Résultats (votes et %) |

### Billetterie
| Méthode | Route | Description |
|---|---|---|
| POST / GET | `/events/{id}/ticket-types` | Créer / lister les types (vendus, restants) |
| GET / PATCH / DELETE | `/ticket-types/{id}` | Type de billet |
| POST | `/ticket-types/{id}/tickets` | Acheter un billet |
| GET | `/events/{id}/tickets?ticket_type_id=&email=` | Billets vendus |
| GET / PATCH / DELETE | `/tickets/{id}` | Billet (détail / corriger l'acheteur / annuler) |

### Shopping list
| Méthode | Route | Description |
|---|---|---|
| POST / GET | `/events/{id}/shopping-items` | Ajouter / lister |
| GET / PATCH / DELETE | `/shopping-items/{id}` | Article |

### Covoiturage (bonus)
| Méthode | Route | Description |
|---|---|---|
| POST / GET | `/events/{id}/carpools?available_only=` | Proposer / lister les trajets |
| GET / PATCH / DELETE | `/carpools/{id}` | Trajet |
| POST | `/carpools/{id}/bookings` | Réserver une place |
| DELETE | `/carpools/{id}/bookings/{passenger_id}` | Annuler une réservation |

## Structure

```
run.py             # lancement HTTPS (uvicorn + TLS)
.env.example       # modèle de configuration (copier en .env)
app/
  main.py          # application FastAPI, middlewares, gestion des erreurs
  config.py        # configuration lue depuis .env
  security.py      # bcrypt, politique de mot de passe, JWT
  middleware.py    # en-têtes de sécurité, limitation de débit, taille des requêtes
  deps.py          # utilisateur courant, contrôles d'accès, helpers
  database.py      # moteur SQLAlchemy (SQLite, clés étrangères activées)
  models.py        # modèle de données
  schemas/         # schémas Pydantic par domaine
  routers/         # endpoints par domaine
scripts/
  build_postman.py # génération de la collection Postman
  generate_cert.py # certificat HTTPS auto-signé
  promote_admin.py # passer un utilisateur administrateur
docs/              # collection Postman
tests/             # tests pytest (dont test_security.py)
```
