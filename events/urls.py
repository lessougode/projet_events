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
]
