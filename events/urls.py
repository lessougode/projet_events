from django.urls import path
from django.contrib.auth import views as auth_views
from . import views
from .forms import OrganisateurAuthenticationForm

urlpatterns = [
    # --- Espace public ---
    path("", views.liste_evenements, name="liste_evenements"),
    path("evenement/<int:pk>/", views.detail_evenement, name="detail_evenement"),
    path("evenement/<int:pk>/inscription/", views.inscription_evenement, name="inscription_evenement"),
    path("evenement/<int:pk>/verifiez-votre-email/", views.verifier_votre_email, name="verifier_votre_email"),
    path("confirmation/<str:token>/", views.confirmer_inscription, name="confirmer_inscription"),

    # --- Paiement d'une inscription payante ---
    path("paiement/<str:token>/", views.choisir_paiement_inscription, name="choisir_paiement_inscription"),
    path("paiement/<str:token>/preuve/<int:compte_id>/", views.soumettre_preuve_inscription, name="soumettre_preuve_inscription"),
    path("paiement/<str:token>/cinetpay/<int:compte_id>/", views.payer_cinetpay_inscription, name="payer_cinetpay_inscription"),
    path("paiement/<str:token>/cinetpay/retour/", views.cinetpay_retour_inscription, name="cinetpay_retour_inscription"),
    path("paiement/<str:token>/soumis/", views.paiement_soumis, name="paiement_soumis"),

    # --- Publications publiques ---
    path("publications/", views.liste_publications, name="liste_publications"),

    # --- Authentification organisateur ---
    path("organisateur/inscription/", views.inscription_organisateur, name="inscription_organisateur"),
    path("organisateur/compte-en-attente/", views.compte_en_attente, name="compte_en_attente"),
    path(
        "organisateur/connexion/",
        auth_views.LoginView.as_view(template_name="events/connexion.html", authentication_form=OrganisateurAuthenticationForm),
        name="connexion",
    ),
    path("organisateur/deconnexion/", auth_views.LogoutView.as_view(next_page="liste_evenements"), name="deconnexion"),

    # --- Espace organisateur (protégé) ---
    path("organisateur/dashboard/", views.dashboard_organisateur, name="dashboard_organisateur"),
    path("organisateur/evenements/creer/", views.creer_evenement, name="creer_evenement"),
    path("organisateur/evenements/<int:pk>/modifier/", views.modifier_evenement, name="modifier_evenement"),
    path("organisateur/evenements/<int:pk>/supprimer/", views.supprimer_evenement, name="supprimer_evenement"),
    path("organisateur/evenements/<int:pk>/inscrits/", views.liste_inscrits, name="liste_inscrits"),
    path("organisateur/evenements/<int:pk>/inscrits/excel/", views.telecharger_excel_inscrits, name="telecharger_excel_inscrits"),

    # --- Moyens de paiement & paiements reçus (événements payants) ---
    path("organisateur/moyens-paiement/", views.organisateur_moyens_paiement, name="organisateur_moyens_paiement"),
    path("organisateur/paiements-recus/", views.organisateur_paiements_recus, name="organisateur_paiements_recus"),
    path("organisateur/paiements-recus/<int:pk>/valider/", views.valider_paiement_recu, name="valider_paiement_recu"),
    path("organisateur/paiements-recus/<int:pk>/refuser/", views.refuser_paiement_recu, name="refuser_paiement_recu"),

    # --- Abonnement organisateur (= commerçant) ---
    path("organisateur/abonnement/", views.organisateur_abonnement, name="organisateur_abonnement"),
    path("organisateur/abonnement/retrouver-compte/", views.retrouver_compte_abonnement, name="retrouver_compte_abonnement"),
    path("organisateur/abonnement/preuve/<int:compte_id>/", views.soumettre_preuve_abonnement, name="soumettre_preuve_abonnement"),
    path("organisateur/abonnement/cinetpay/<int:compte_id>/", views.payer_cinetpay_abonnement, name="payer_cinetpay_abonnement"),
    path("organisateur/abonnement/cinetpay/retour/", views.cinetpay_retour_abonnement, name="cinetpay_retour_abonnement"),

    # --- Publications ---
    path("organisateur/publications/", views.organisateur_publications, name="organisateur_publications"),
    path("organisateur/publications/creer/", views.creer_publication, name="creer_publication"),
    path("organisateur/publications/<int:pk>/supprimer/", views.supprimer_publication, name="supprimer_publication"),
]
