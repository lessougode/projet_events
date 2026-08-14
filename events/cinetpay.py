"""
Client CinetPay minimal — events/cinetpay.py
---------------------------------------------
Deux appels seulement :
  - initier_paiement(...)  : POST /v2/payment      -> renvoie l'URL de paiement
  - verifier_transaction() : POST /v2/payment/check -> statut réel côté CinetPay

IMPORTANT (sécurité) : on ne fait JAMAIS confiance aux paramètres de l'URL
de retour envoyés par le navigateur du payeur (facilement falsifiables).
Après un retour de paiement, on appelle systématiquement
verifier_transaction() pour connaître le statut réel avant de valider quoi
que ce soit. Voir events/views.py (vues cinetpay_retour_*).

Configuration attendue dans le .env :
  CINETPAY_API_KEY
  CINETPAY_SITE_ID
  CINETPAY_SECRET_KEY   (utilisée uniquement si on active le webhook de
                          notification HMAC — non obligatoire pour le
                          circuit "vérification systématique côté serveur")

NOTE : le module `requests` est importé à l'intérieur des fonctions (pas en
haut du fichier). Ainsi, si `requests` n'est pas installé (ex : pas de
connexion internet pour `pip install`), seul CinetPay est indisponible —
le reste du site (Mobile Money direct, événements, publications...)
continue de fonctionner normalement.
"""

from django.conf import settings

BASE_URL = "https://api-checkout.cinetpay.com/v2"


class CinetPayError(Exception):
    """Levée quand CinetPay renvoie une erreur, une réponse inattendue,
    ou quand le paquet `requests` n'est pas installé."""


def est_configure():
    """True si les identifiants CinetPay sont renseignés côté serveur."""
    return bool(settings.CINETPAY_API_KEY and settings.CINETPAY_SITE_ID)


def _get_requests():
    try:
        import requests
        return requests
    except ImportError as exc:
        raise CinetPayError(
            "Le paquet 'requests' n'est pas installé (pip install requests). "
            "CinetPay est momentanément indisponible ; le Mobile Money direct reste utilisable."
        ) from exc


def initier_paiement(*, transaction_id, montant, description, url_retour, url_notification=None,
                      client_nom="", client_email="", client_telephone="", devise="XOF"):
    """Démarre un paiement CinetPay et renvoie l'URL vers laquelle rediriger
    le payeur (payment_url). Lève CinetPayError en cas d'échec."""
    requests = _get_requests()
    payload = {
        "apikey": settings.CINETPAY_API_KEY,
        "site_id": settings.CINETPAY_SITE_ID,
        "transaction_id": transaction_id,
        "amount": int(montant),
        "currency": devise,
        "description": description[:255],
        "return_url": url_retour,
        "notify_url": url_notification or url_retour,
        "channels": "ALL",
        "customer_name": client_nom or "Client",
        "customer_surname": "",
        "customer_email": client_email or "client@example.com",
        "customer_phone_number": client_telephone or "",
    }
    try:
        reponse = requests.post(f"{BASE_URL}/payment", json=payload, timeout=15)
        data = reponse.json()
    except (requests.RequestException, ValueError) as exc:
        raise CinetPayError(f"Impossible de contacter CinetPay : {exc}") from exc

    if data.get("code") != "201":
        raise CinetPayError(data.get("message", "Erreur inconnue lors de l'initialisation du paiement CinetPay."))

    return data["data"]["payment_url"]


def verifier_transaction(transaction_id):
    """Interroge CinetPay pour connaître le statut RÉEL d'une transaction.
    Renvoie un dict {"payee": bool, "statut": str, "montant": Decimal|None, "brut": dict}."""
    requests = _get_requests()
    payload = {
        "apikey": settings.CINETPAY_API_KEY,
        "site_id": settings.CINETPAY_SITE_ID,
        "transaction_id": transaction_id,
    }
    try:
        reponse = requests.post(f"{BASE_URL}/payment/check", json=payload, timeout=15)
        data = reponse.json()
    except (requests.RequestException, ValueError) as exc:
        raise CinetPayError(f"Impossible de vérifier la transaction CinetPay : {exc}") from exc

    infos = data.get("data", {}) or {}
    statut = infos.get("status", "")  # "ACCEPTED" si payé
    return {
        "payee": data.get("code") == "00" and statut == "ACCEPTED",
        "statut": statut or data.get("message", "INCONNU"),
        "montant": infos.get("amount"),
        "brut": data,
    }
