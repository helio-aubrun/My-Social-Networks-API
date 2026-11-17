import json
import os
import re
import secrets
import sys
import warnings
from pathlib import Path
from urllib.parse import urlencode

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ["DATABASE_URL"] = "sqlite://"
os.environ.setdefault("JWT_SECRET", secrets.token_urlsafe(48))
os.environ["BCRYPT_ROUNDS"] = "4"
warnings.filterwarnings("ignore")

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.main import app

OUTPUT = ROOT / "docs" / "My-Social-Networks-API.postman_collection.json"
BASE_URL = "https://localhost:8443"
PASSWORD = "MotDePasse1"
ACTORS = ("alice", "bob", "carol", "dave", "temp")

COLLECTION_DESCRIPTION = """\
# My Social Networks API

API REST de gestion d'un réseau social : utilisateurs, événements, groupes, fils de discussion,
albums photo, sondages, billetterie, shopping list et covoiturage.

## Utilisation
1. Lancer l'API en HTTPS : `python run.py` (base `social_networks.db` vide).
2. Le certificat de développement est auto-signé : désactiver *SSL certificate verification*
   dans les réglages Postman (ou importer `certs/cert.pem`).
3. Variable `baseUrl` : `https://localhost:8443` par défaut.
4. Exécuter la collection **dans l'ordre** (Collection Runner). Le dossier *Authentification* crée
   les utilisateurs puis enregistre leur jeton dans les variables `token_alice`, `token_bob`…
   Chaque requête vérifie le code HTTP attendu.

## Sécurité
- **JWT** (HS256, durée limitée) : `POST /auth/login` puis en-tête `Authorization: Bearer <token>`.
  Toutes les routes sont protégées sauf l'inscription (`POST /users`), la connexion et l'achat
  de billet (personne extérieure).
- L'auteur d'une action est toujours l'utilisateur du jeton (impossible d'agir au nom d'un autre).
- Droits : soi-même ou administrateur pour un compte ; organisateurs pour un événement ;
  administrateurs pour un groupe ; auteur (ou modérateur) pour un message, une photo, un commentaire.
- Contenus privés (événements privés, groupes secrets) : 404 pour les non-invités.
- Mots de passe hachés avec bcrypt, 8 caractères minimum dont majuscule, minuscule et chiffre.
- Limitation de débit : 1000 requêtes / heure / IP et 5 échecs de connexion / 15 min / IP (429).
- Corps de requête limité à 10 Ko (413), en-têtes de sécurité HTTP, CORS restreint.

## Conventions
- JSON en entrée et en sortie ; dates au format ISO 8601 (UTC).
- `PATCH` = mise à jour partielle. Pagination des listes : `skip` / `limit`.

## Codes de retour
| Code | Signification |
|------|---------------|
| 200 / 201 / 204 | Succès (lecture-modification / création / suppression) |
| 401 | Jeton absent, invalide ou expiré ; identifiants incorrects |
| 403 | Action interdite pour cet utilisateur |
| 404 | Ressource introuvable (ou privée) |
| 409 | Conflit avec une règle métier (email déjà utilisé, billet épuisé, dernier organisateur…) |
| 413 | Corps de requête trop volumineux |
| 422 | Données invalides (champ manquant, mot de passe trop faible, dates incohérentes…) |
| 429 | Trop de requêtes |

Les erreurs renvoient `{"detail": "<message>"}`.
"""

FOLDER_DESCRIPTIONS = {
    "Authentification": "Inscription (route publique) et connexion : le jeton JWT de chaque utilisateur "
                        "est enregistré dans une variable de collection (`token_alice`, `token_bob`…).",
    "Utilisateurs": "CRUDS des utilisateurs. L'email est unique (insensible à la casse) ; un compte ne peut "
                    "être modifié ou supprimé que par son propriétaire ou un administrateur.",
    "Groupes": "Groupes public / privé / secret. Le créateur est administrateur d'office ; seuls les "
               "administrateurs gèrent le groupe. Paramètres : autoriser les membres à publier et à créer des événements.",
    "Événements": "Étape 1 de création : nom, description, dates, lieu, photo de couverture, visibilité, "
                  "organisateurs et participants. Le créateur est organisateur d'office ; seuls les organisateurs "
                  "modifient l'événement. Les événements privés ne sont visibles que de leurs invités.",
    "Fils de discussion": "Un fil est lié à un groupe OU à un événement. Messages publiés par les membres / "
                          "participants, commentables par eux ; modification par l'auteur, suppression par "
                          "l'auteur ou un modérateur.",
    "Albums photo": "Albums d'un événement (créés par les organisateurs) ; photos postées et commentées "
                    "par ses participants.",
    "Sondages": "Créés par un organisateur ; 1+ questions, une seule réponse par question et par participant.",
    "Billetterie": "Événements publics : types de billets (nom, montant, quantité limitée) gérés par les "
                   "organisateurs ; achat public, 1 billet par personne extérieure (email) et par événement. "
                   "Les données des acheteurs ne sont visibles que des organisateurs.",
    "Shopping list": "Si activée : ce que chaque participant apporte (nom unique par événement, quantité, heure d'arrivée).",
    "Covoiturage (bonus)": "Si activé : trajets proposés par les participants et réservation de places.",
    "Tableaux de bord": "Endpoints de mise à disposition de données agrégées : statistiques d'un événement "
                        "(organisateurs), résultats de sondage, événements d'un utilisateur.",
}

DT = "2026-12-12T{}:00"


def scenario():
    AU, U, G, E, T, A, P, B, S, C, D = (
        "Authentification", "Utilisateurs", "Groupes", "Événements", "Fils de discussion", "Albums photo",
        "Sondages", "Billetterie", "Shopping list", "Covoiturage (bonus)", "Tableaux de bord",
    )
    user = lambda first, last, email: {
        "first_name": first, "last_name": last, "email": email, "password": PASSWORD,
        "bio": f"Bonjour, je suis {first}.", "avatar_url": f"https://picsum.photos/seed/{first}/200",
    }
    login = lambda email: {"email": email, "password": PASSWORD}
    buyer = lambda first, last, email, street, cp, city: {
        "first_name": first, "last_name": last, "email": email,
        "street": street, "postal_code": cp, "city": city, "country": "France",
    }
    jean = buyer("Jean", "Dupont", "jean.dupont@mail.fr", "4 avenue Jean Jaurès", "69007", "Lyon")
    marie = buyer("Marie", "Curie", "marie@mail.fr", "1 rue Pierre", "75005", "Paris")
    return [
        (AU, "Inscription (Alice)", None, "POST", "/users", user("Alice", "Martin", "alice@example.com"), None),
        (AU, "Inscription (Bob)", None, "POST", "/users", user("Bob", "Durand", "bob@example.com"), None),
        (AU, "Inscription (Carol)", None, "POST", "/users", user("Carol", "Petit", "carol@example.com"), None),
        (AU, "Inscription (Dave)", None, "POST", "/users", user("Dave", "Leroy", "dave@example.com"), None),
        (AU, "Inscription (compte temporaire)", None, "POST", "/users", user("Temp", "Oraire", "temp@example.com"), None),
        (AU, "Inscription – mot de passe trop faible (422)", None, "POST", "/users",
         {**user("Eve", "Faible", "eve@example.com"), "password": "azerty"}, None),
        (AU, "Connexion (Alice)", None, "POST", "/auth/login", login("alice@example.com"), None),
        (AU, "Connexion (Bob)", None, "POST", "/auth/login", login("bob@example.com"), None),
        (AU, "Connexion (Carol)", None, "POST", "/auth/login", login("carol@example.com"), None),
        (AU, "Connexion (Dave)", None, "POST", "/auth/login", login("dave@example.com"), None),
        (AU, "Connexion (compte temporaire)", None, "POST", "/auth/login", login("temp@example.com"), None),
        (AU, "Connexion – mauvais mot de passe (401)", None, "POST", "/auth/login",
         {"email": "alice@example.com", "password": "Mauvais123"}, None),
        (AU, "Profil de l'utilisateur connecté", "alice", "GET", "/auth/me", None, None),
        (AU, "Accès sans jeton (401)", None, "GET", "/users", None, None),

        (U, "Inscription – email déjà utilisé (409)", None, "POST", "/users",
         user("Alice", "Bis", "ALICE@example.com"), None),
        (U, "Lister / rechercher des utilisateurs", "alice", "GET", "/users", None, {"q": "a", "limit": 10}),
        (U, "Détail d'un utilisateur", "alice", "GET", "/users/1", None, None),
        (U, "Modifier son profil", "bob", "PATCH", "/users/2", {"bio": "Fan de randonnée"}, None),
        (U, "Modifier le profil d'un autre (403)", "bob", "PATCH", "/users/1", {"bio": "Piraté"}, None),
        (U, "Supprimer son compte", "temp", "DELETE", "/users/5", None, None),

        (G, "Créer un groupe", "alice", "POST", "/groups", {
            "name": "Club rando Lyon", "description": "Sorties nature chaque week-end",
            "icon": "https://picsum.photos/seed/icon/64", "cover_photo": "https://picsum.photos/seed/rando/1200/400",
            "type": "public", "allow_member_posts": True, "allow_member_events": True, "member_ids": [2, 3],
        }, None),
        (G, "Créer un groupe secret", "bob", "POST", "/groups", {
            "name": "Comité surprise", "type": "secret", "allow_member_posts": False,
            "allow_member_events": False, "member_ids": [3],
        }, None),
        (G, "Lister les groupes (non-membre : groupes secrets masqués)", "dave", "GET", "/groups", None, None),
        (G, "Lister les groupes vus par un membre du groupe secret", "carol", "GET", "/groups", None, None),
        (G, "Détail d'un groupe", "alice", "GET", "/groups/1", None, None),
        (G, "Détail d'un groupe secret – non-membre (404)", "dave", "GET", "/groups/2", None, None),
        (G, "Modifier les paramètres d'un groupe", "alice", "PATCH", "/groups/1",
         {"description": "Randonnées et bivouacs autour de Lyon"}, None),
        (G, "Modifier un groupe – simple membre (403)", "bob", "PATCH", "/groups/1", {"name": "Piraté"}, None),
        (G, "Rejoindre un groupe public", "dave", "POST", "/groups/1/members/4", None, None),
        (G, "Nommer un administrateur", "alice", "POST", "/groups/1/admins/2", None, None),
        (G, "Retirer un administrateur", "alice", "DELETE", "/groups/1/admins/2", None, None),
        (G, "Retirer le dernier administrateur (409)", "bob", "DELETE", "/groups/2/admins/2", None, None),
        (G, "Groupes d'un utilisateur", "carol", "GET", "/users/3/groups", None, None),
        (G, "Quitter un groupe", "dave", "DELETE", "/groups/1/members/4", None, None),
        (G, "Créer un groupe temporaire", "dave", "POST", "/groups", {"name": "Groupe test"}, None),
        (G, "Supprimer un groupe", "dave", "DELETE", "/groups/3", None, None),

        (E, "Créer un événement (étape 1)", "alice", "POST", "/events", {
            "name": "Soirée jeux de société", "description": "Jeux, pizzas et bonne humeur. Apportez vos jeux !",
            "start_date": DT.format("19:00"), "end_date": DT.format("23:30"),
            "location": "12 rue de la République, 69002 Lyon",
            "cover_photo": "https://picsum.photos/seed/jeux/1200/400", "visibility": "private",
            "participant_ids": [2, 3], "shopping_list_enabled": True, "carpool_enabled": True,
        }, None),
        (E, "Créer un événement de groupe (invitation de tous les membres)", "alice", "POST", "/events", {
            "name": "Randonnée au Mont Pilat", "description": "Boucle de 15 km, niveau moyen.",
            "start_date": "2026-12-20T08:00:00", "end_date": "2026-12-20T17:00:00",
            "location": "Parking du Crêt de l'Œillon", "visibility": "public",
            "group_id": 1, "invite_group_members": True,
        }, None),
        (E, "Créer un événement public avec billetterie", "bob", "POST", "/events", {
            "name": "Concert caritatif", "description": "Trois groupes locaux au profit des Restos du Cœur.",
            "start_date": "2027-01-15T20:00:00", "end_date": "2027-01-15T23:59:00",
            "location": "Salle des fêtes, Villeurbanne", "cover_photo": "https://picsum.photos/seed/concert/1200/400",
            "visibility": "public", "ticketing_enabled": True,
        }, None),
        (E, "Créer un événement – date de fin avant la date de début (422)", "alice", "POST", "/events", {
            "name": "Erreur", "description": "x", "start_date": DT.format("20:00"), "end_date": DT.format("18:00"),
            "location": "Lyon",
        }, None),
        (E, "Rechercher des événements (non-invité : publics uniquement)", "dave", "GET", "/events", None, None),
        (E, "Rechercher des événements visibles par un invité", "bob", "GET", "/events", None,
         {"starts_after": "2026-12-01T00:00:00"}),
        (E, "Détail d'un événement", "bob", "GET", "/events/1", None, None),
        (E, "Détail d'un événement privé – non-invité (404)", "dave", "GET", "/events/1", None, None),
        (E, "Modifier un événement", "alice", "PATCH", "/events/1", {"location": "8 place Bellecour, 69002 Lyon"}, None),
        (E, "Modifier un événement – participant (403)", "bob", "PATCH", "/events/1", {"name": "Piraté"}, None),
        (E, "Ajouter un organisateur", "alice", "POST", "/events/1/organizers/2", None, None),
        (E, "Retirer un organisateur", "alice", "DELETE", "/events/1/organizers/2", None, None),
        (E, "Ajouter un participant", "alice", "POST", "/events/1/participants/2", None, None),
        (E, "Inviter un participant (Dave)", "alice", "POST", "/events/1/participants/4", None, None),
        (E, "Se retirer d'un événement", "dave", "DELETE", "/events/1/participants/4", None, None),
        (E, "S'inscrire à un événement public", "dave", "POST", "/events/3/participants/4", None, None),
        (E, "Inviter tous les membres du groupe en un clic", "alice", "POST", "/events/2/invite-group-members", None, None),
        (E, "Partager un événement public sur les réseaux sociaux", "bob", "GET", "/events/2/share", None, None),
        (E, "Partager un événement privé (403)", "alice", "GET", "/events/1/share", None, None),
        (E, "Événements d'un utilisateur", "bob", "GET", "/users/2/events", None, {"role": "all"}),
        (E, "Événements d'un groupe", "alice", "GET", "/groups/1/events", None, None),
        (E, "Créer un événement temporaire", "dave", "POST", "/events", {
            "name": "Brouillon", "description": "À supprimer", "start_date": DT.format("10:00"),
            "end_date": DT.format("11:00"), "location": "Lyon",
        }, None),
        (E, "Supprimer un événement", "dave", "DELETE", "/events/4", None, None),

        (T, "Fil du groupe (créé automatiquement)", "alice", "GET", "/threads", None, {"group_id": 1}),
        (T, "Créer le fil d'un événement", "alice", "POST", "/threads",
         {"event_id": 1, "title": "Organisation de la soirée"}, None),
        (T, "Créer un fil lié à un groupe ET un événement (422)", "alice", "POST", "/threads",
         {"group_id": 1, "event_id": 2}, None),
        (T, "Détail d'un fil", "bob", "GET", "/threads/3", None, None),
        (T, "Renommer un fil", "alice", "PATCH", "/threads/3", {"title": "Orga soirée jeux"}, None),
        (T, "Publier un message", "bob", "POST", "/threads/3/messages", {"content": "J'apporte Catan et Dixit !"}, None),
        (T, "Publier un message – événement privé non accessible (404)", "dave", "POST", "/threads/3/messages",
         {"content": "Je peux venir ?"}, None),
        (T, "Publier dans un groupe réservé aux admins – membre (403)", "carol", "POST", "/threads/2/messages",
         {"content": "Coucou"}, None),
        (T, "Commenter un message", "carol", "POST", "/messages/1/comments", {"content": "Génial, j'adore Dixit"}, None),
        (T, "Lister les messages d'un fil", "carol", "GET", "/threads/3/messages", None, None),
        (T, "Détail d'un message", "bob", "GET", "/messages/1", None, None),
        (T, "Modifier son message", "bob", "PATCH", "/messages/1", {"content": "J'apporte Catan, Dixit et Codenames !"}, None),
        (T, "Modifier le message d'un autre (403)", "alice", "PATCH", "/messages/1", {"content": "Piraté"}, None),
        (T, "Lister les commentaires d'un message", "bob", "GET", "/messages/1/comments", None, None),
        (T, "Modifier son commentaire", "carol", "PATCH", "/message-comments/1", {"content": "Génial, j'adore Codenames"}, None),
        (T, "Supprimer son commentaire", "carol", "DELETE", "/message-comments/1", None, None),
        (T, "Publier un message (Carol)", "carol", "POST", "/threads/3/messages", {"content": "Message à modérer"}, None),
        (T, "Supprimer un message (modération par l'organisateur)", "alice", "DELETE", "/messages/2", None, None),
        (T, "Créer le fil d'un autre événement", "bob", "POST", "/threads", {"event_id": 3}, None),
        (T, "Lister les fils d'un événement", "bob", "GET", "/threads", None, {"event_id": 3}),
        (T, "Supprimer un fil", "bob", "DELETE", "/threads/4", None, None),

        (A, "Créer un album", "alice", "POST", "/events/1/albums",
         {"name": "Photos de la soirée", "description": "Vos meilleurs clichés"}, None),
        (A, "Lister les albums d'un événement", "bob", "GET", "/events/1/albums", None, None),
        (A, "Modifier un album", "alice", "PATCH", "/albums/1", {"description": "Souvenirs de la soirée jeux"}, None),
        (A, "Poster une photo", "bob", "POST", "/albums/1/photos",
         {"url": "https://picsum.photos/seed/p1/800/600", "caption": "Partie de Catan"}, None),
        (A, "Poster une photo – URL non http(s) (422)", "bob", "POST", "/albums/1/photos",
         {"url": "javascript:alert(1)"}, None),
        (A, "Poster une photo – non-invité (404)", "dave", "POST", "/albums/1/photos",
         {"url": "https://picsum.photos/seed/p2/800/600"}, None),
        (A, "Commenter une photo", "carol", "POST", "/photos/1/comments", {"content": "Quelle partie !"}, None),
        (A, "Lister les photos d'un album", "carol", "GET", "/albums/1/photos", None, None),
        (A, "Détail d'une photo", "bob", "GET", "/photos/1", None, None),
        (A, "Modifier sa photo", "bob", "PATCH", "/photos/1", {"caption": "Victoire de Bob à Catan"}, None),
        (A, "Lister les commentaires d'une photo", "bob", "GET", "/photos/1/comments", None, None),
        (A, "Modifier son commentaire de photo", "carol", "PATCH", "/photo-comments/1", {"content": "Bravo Bob !"}, None),
        (A, "Détail d'un album", "alice", "GET", "/albums/1", None, None),
        (A, "Supprimer son commentaire de photo", "carol", "DELETE", "/photo-comments/1", None, None),
        (A, "Poster une photo (Carol)", "carol", "POST", "/albums/1/photos",
         {"url": "https://picsum.photos/seed/p3/800/600"}, None),
        (A, "Supprimer une photo (organisateur)", "alice", "DELETE", "/photos/2", None, None),
        (A, "Créer un album temporaire", "alice", "POST", "/events/1/albums", {"name": "Brouillon"}, None),
        (A, "Supprimer un album", "alice", "DELETE", "/albums/2", None, None),

        (P, "Créer un sondage (organisateur)", "alice", "POST", "/events/1/polls", {
            "title": "Préparatifs",
            "questions": [
                {"text": "Que mange-t-on ?", "options": ["Pizzas", "Raclette", "Burgers"]},
                {"text": "À quelle heure commence-t-on ?", "options": ["19h", "20h"]},
            ],
        }, None),
        (P, "Créer un sondage – participant (403)", "carol", "POST", "/events/1/polls",
         {"title": "x", "questions": [{"text": "?", "options": ["a", "b"]}]}, None),
        (P, "Lister les sondages d'un événement", "bob", "GET", "/events/1/polls", None, None),
        (P, "Détail d'un sondage", "bob", "GET", "/polls/1", None, None),
        (P, "Répondre à un sondage (Bob)", "bob", "PUT", "/polls/1/responses",
         {"answers": [{"question_id": 1, "option_id": 2}, {"question_id": 2, "option_id": 4}]}, None),
        (P, "Répondre à un sondage (Carol)", "carol", "PUT", "/polls/1/responses",
         {"answers": [{"question_id": 1, "option_id": 2}, {"question_id": 2, "option_id": 5}]}, None),
        (P, "Répondre – deux réponses à la même question (422)", "carol", "PUT", "/polls/1/responses",
         {"answers": [{"question_id": 1, "option_id": 1}, {"question_id": 1, "option_id": 2}]}, None),
        (P, "Lister les réponses (organisateur : toutes)", "alice", "GET", "/polls/1/responses", None, None),
        (P, "Lister les réponses (participant : la sienne)", "bob", "GET", "/polls/1/responses", None, None),
        (P, "Résultats du sondage", "bob", "GET", "/polls/1/results", None, None),
        (P, "Modifier le titre d'un sondage", "alice", "PATCH", "/polls/1", {"title": "Préparatifs de la soirée"}, None),
        (P, "Supprimer sa réponse", "carol", "DELETE", "/polls/1/responses/3", None, None),
        (P, "Créer un sondage temporaire", "alice", "POST", "/events/1/polls",
         {"title": "Test", "questions": [{"text": "Oui ou non ?", "options": ["Oui", "Non"]}]}, None),
        (P, "Supprimer un sondage", "alice", "DELETE", "/polls/2", None, None),

        (B, "Créer un type de billet (Standard)", "bob", "POST", "/events/3/ticket-types",
         {"name": "Standard", "price": 15, "quantity": 200}, None),
        (B, "Créer un type de billet (VIP)", "bob", "POST", "/events/3/ticket-types",
         {"name": "VIP", "price": 45.5, "quantity": 1}, None),
        (B, "Créer un type de billet – billetterie désactivée (409)", "alice", "POST", "/events/1/ticket-types",
         {"name": "Standard", "price": 10, "quantity": 10}, None),
        (B, "Lister les types de billets", "dave", "GET", "/events/3/ticket-types", None, None),
        (B, "Modifier un type de billet", "bob", "PATCH", "/ticket-types/1", {"price": 12}, None),
        (B, "Acheter un billet (public, sans compte)", None, "POST", "/ticket-types/2/tickets", jean, None),
        (B, "Acheter un second billet – même personne (409)", None, "POST", "/ticket-types/1/tickets", jean, None),
        (B, "Acheter un billet – type épuisé (409)", None, "POST", "/ticket-types/2/tickets", marie, None),
        (B, "Lister les billets vendus (organisateur)", "bob", "GET", "/events/3/tickets", None, None),
        (B, "Lister les billets vendus – non organisateur (403)", "dave", "GET", "/events/3/tickets", None, None),
        (B, "Détail d'un billet", "bob", "GET", "/tickets/1", None, None),
        (B, "Corriger l'adresse d'un acheteur", "bob", "PATCH", "/tickets/1", {"street": "6 avenue Jean Jaurès"}, None),
        (B, "Détail d'un type de billet", "dave", "GET", "/ticket-types/2", None, None),
        (B, "Acheter un billet Standard", None, "POST", "/ticket-types/1/tickets", marie, None),
        (B, "Billet d'une personne (recherche par email)", "bob", "GET", "/events/3/tickets", None,
         {"email": "marie@mail.fr"}),
        (B, "Annuler un billet", "bob", "DELETE", "/tickets/2", None, None),
        (B, "Supprimer un type de billet déjà vendu (409)", "bob", "DELETE", "/ticket-types/2", None, None),
        (B, "Créer un type de billet temporaire", "bob", "POST", "/events/3/ticket-types",
         {"name": "Early bird", "price": 8, "quantity": 20}, None),
        (B, "Supprimer un type de billet", "bob", "DELETE", "/ticket-types/3", None, None),

        (S, "Ajouter un article", "bob", "POST", "/events/1/shopping-items",
         {"name": "Chips", "quantity": 4, "arrival_time": DT.format("18:45")}, None),
        (S, "Ajouter un article déjà apporté (409)", "carol", "POST", "/events/1/shopping-items",
         {"name": "chips", "quantity": 2, "arrival_time": DT.format("19:15")}, None),
        (S, "Ajouter un article (Carol)", "carol", "POST", "/events/1/shopping-items",
         {"name": "Jus de pomme", "quantity": 2, "arrival_time": DT.format("19:15")}, None),
        (S, "Lister la shopping list", "alice", "GET", "/events/1/shopping-items", None, None),
        (S, "Détail d'un article", "alice", "GET", "/shopping-items/1", None, None),
        (S, "Modifier son article", "bob", "PATCH", "/shopping-items/1", {"quantity": 6}, None),
        (S, "Modifier l'article d'un autre (403)", "carol", "PATCH", "/shopping-items/1", {"quantity": 1}, None),
        (S, "Supprimer son article", "carol", "DELETE", "/shopping-items/2", None, None),

        (C, "Proposer un trajet", "bob", "POST", "/events/1/carpools", {
            "departure_location": "Gare de Villeurbanne", "departure_time": DT.format("18:15"),
            "price": 3.5, "seats": 3, "max_detour_minutes": 15,
        }, None),
        (C, "Réserver une place", "carol", "POST", "/carpools/1/bookings", None, None),
        (C, "Réserver son propre trajet (409)", "bob", "POST", "/carpools/1/bookings", None, None),
        (C, "Lister les trajets avec places libres", "alice", "GET", "/events/1/carpools", None, {"available_only": True}),
        (C, "Détail d'un trajet", "carol", "GET", "/carpools/1", None, None),
        (C, "Modifier son trajet", "bob", "PATCH", "/carpools/1", {"seats": 2}, None),
        (C, "Annuler sa réservation", "carol", "DELETE", "/carpools/1/bookings/3", None, None),
        (C, "Réserver à nouveau une place", "carol", "POST", "/carpools/1/bookings", None, None),
        (C, "Proposer un trajet temporaire", "carol", "POST", "/events/1/carpools", {
            "departure_location": "Part-Dieu", "departure_time": DT.format("18:30"),
            "price": 0, "seats": 2, "max_detour_minutes": 10,
        }, None),
        (C, "Supprimer son trajet", "carol", "DELETE", "/carpools/2", None, None),

        (D, "Statistiques d'un événement", "alice", "GET", "/events/1/stats", None, None),
        (D, "Statistiques de l'événement avec billetterie", "bob", "GET", "/events/3/stats", None, None),
        (D, "Statistiques – non organisateur (403)", "carol", "GET", "/events/1/stats", None, None),
        (D, "Résultats du sondage", "carol", "GET", "/polls/1/results", None, None),
        (D, "Événements d'un utilisateur (organisateur)", "alice", "GET", "/users/1/events", None, {"role": "organizer"}),
    ]


def _route_for(method: str, path: str) -> dict | None:
    for template, operations in app.openapi()["paths"].items():
        pattern = "^" + re.sub(r"\{[^}]+\}", r"[^/]+", template) + "$"
        if re.match(pattern, path) and method.lower() in operations:
            return {"path": template, **operations[method.lower()]}
    return None


def _url(path: str, params: dict | None) -> dict:
    query = [{"key": k, "value": str(v).lower() if isinstance(v, bool) else str(v)} for k, v in (params or {}).items()]
    raw = "{{baseUrl}}" + path + ("?" + urlencode({q["key"]: q["value"] for q in query}) if query else "")
    url = {"raw": raw, "host": ["{{baseUrl}}"], "path": [p for p in path.split("/") if p]}
    if query:
        url["query"] = query
    return url


def _login_actor(name: str, body: dict | None) -> str | None:
    if body and "email" in body and "password" in body and body["password"] == PASSWORD:
        actor = body["email"].split("@")[0]
        return actor if actor in ACTORS else None
    return None


def _item(name, actor, method, path, body, params, response, route):
    headers = []
    if actor is not None:
        headers.append({"key": "Authorization", "value": f"Bearer {{{{token_{actor}}}}}"})
    if body is not None:
        headers.append({"key": "Content-Type", "value": "application/json"})
    request = {"method": method, "header": headers, "url": _url(path, params)}
    if body is not None:
        request["body"] = {
            "mode": "raw", "raw": json.dumps(body, indent=2, ensure_ascii=False),
            "options": {"raw": {"language": "json"}},
        }
    doc = (route.get("description") or "").strip()
    who = f"\n\n_Exécutée en tant que : **{actor}**_" if actor else "\n\n_Route publique (sans jeton)_" if path in (
        "/users", "/auth/login") or path.endswith("/tickets") else ""
    request["description"] = f"**{method} `{route['path']}`**\n\n{doc}{who}"

    code = response.status_code
    payload = response.json() if response.content else None
    if isinstance(payload, dict) and "access_token" in payload:
        payload = {**payload, "access_token": "<jeton JWT>"}
    example = {
        "name": f"{code} {response.reason_phrase}",
        "originalRequest": request,
        "status": response.reason_phrase,
        "code": code,
        "_postman_previewlanguage": "json",
        "header": [{"key": "Content-Type", "value": "application/json"}] if response.content else [],
        "body": json.dumps(payload, indent=2, ensure_ascii=False) if payload is not None else "",
    }
    test = [
        f'pm.test("Code HTTP {code}", function () {{',
        f"    pm.response.to.have.status({code});",
        "});",
    ]
    login_actor = _login_actor(name, body) if path == "/auth/login" and code == 200 else None
    if login_actor:
        test.append(f'pm.collectionVariables.set("token_{login_actor}", pm.response.json().access_token);')
    return {
        "name": name,
        "event": [{"listen": "test", "script": {"type": "text/javascript", "exec": test}}],
        "request": request,
        "response": [example],
    }


def build() -> dict:
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False)

    def override_get_db():
        db = Session()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    app.state.rate_limiter.reset()
    client = TestClient(app, base_url=BASE_URL)
    tokens: dict[str, str] = {}

    folders: dict[str, list] = {}
    for folder, name, actor, method, path, body, params in scenario():
        headers = {"Authorization": f"Bearer {tokens[actor]}"} if actor else {}
        response = client.request(method, path, json=body, params=params, headers=headers)
        if response.status_code >= 500:
            raise RuntimeError(f"{method} {path} -> {response.status_code}: {response.text}")
        login_actor = _login_actor(name, body) if path == "/auth/login" else None
        if login_actor and response.status_code == 200:
            tokens[login_actor] = response.json()["access_token"]
        route = _route_for(method, path)
        if route is None:
            raise RuntimeError(f"Aucune route pour {method} {path}")
        folders.setdefault(folder, []).append(_item(name, actor, method, path, body, params, response, route))
        print(f"{response.status_code}  {method:6} {path:40} {actor or '-'}")
    app.dependency_overrides.clear()
    app.state.rate_limiter.reset()

    return {
        "info": {
            "name": "My Social Networks API",
            "description": COLLECTION_DESCRIPTION,
            "schema": "https://schema.getpostman.com/json/collection/v2.1.0/collection.json",
        },
        "variable": [
            {"key": "baseUrl", "value": BASE_URL, "type": "string"},
            *({"key": f"token_{a}", "value": f"<jeton de {a} obtenu via POST /auth/login>", "type": "string"}
              for a in ACTORS),
        ],
        "item": [
            {"name": folder, "description": FOLDER_DESCRIPTIONS.get(folder, ""), "item": items}
            for folder, items in folders.items()
        ],
    }


if __name__ == "__main__":
    collection = build()
    OUTPUT.parent.mkdir(exist_ok=True)
    OUTPUT.write_text(json.dumps(collection, indent=2, ensure_ascii=False), encoding="utf-8")
    total = sum(len(f["item"]) for f in collection["item"])
    print(f"\n{total} requêtes écrites dans {OUTPUT.relative_to(ROOT)}")
