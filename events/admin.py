from django.contrib import admin
from django.contrib.auth import get_user_model
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin
from django.conf import settings
from django.db.models import Count
from django.utils.html import format_html

from .models import (
    Evenement, Inscription, MoyenPaiement, CompteReception, Paiement,
    ConfigurationPlateforme, Abonnement, Publication, PublicationMedia,
)
from utils import send_email_with_template

User = get_user_model()


def _notifier_paiement_traite(paiement):
    """Envoie un email de confirmation/refus après traitement d'un paiement,
    aussi bien pour un abonnement (organisateur) que pour une inscription
    (participant)."""
    if paiement.type_paiement == Paiement.Type.ABONNEMENT and paiement.payeur:
        destinataire = paiement.payeur.email
        nom = paiement.payeur.get_username()
    elif paiement.type_paiement == Paiement.Type.INSCRIPTION and paiement.inscription_id:
        destinataire = paiement.inscription.email
        nom = paiement.inscription.nom_complet
    else:
        return

    if not destinataire:
        return

    if paiement.statut == Paiement.Statut.VALIDE:
        sujet = "Paiement reçu et validé"
        gabarit = "events/email_paiement_confirme.html"
        contexte = {"prenoms": nom, "nom": "", "evenement": ""}
        if paiement.type_paiement == Paiement.Type.INSCRIPTION:
            contexte["evenement"] = paiement.inscription.evenement.titre
            contexte["prenoms"] = paiement.inscription.prenoms
            contexte["nom"] = paiement.inscription.nom
    else:
        sujet = "Paiement non validé"
        gabarit = "events/email_paiement_refuse.html"
        contexte = {"prenoms": nom, "nom": "", "motif": paiement.motif_refus, "evenement": ""}
        if paiement.type_paiement == Paiement.Type.INSCRIPTION:
            contexte["evenement"] = paiement.inscription.evenement.titre
            contexte["prenoms"] = paiement.inscription.prenoms
            contexte["nom"] = paiement.inscription.nom

    try:
        send_email_with_template(sujet, gabarit, contexte, [destinataire], settings.EMAIL_HOST_USER)
    except Exception:
        import traceback
        traceback.print_exc()


class InscriptionInline(admin.TabularInline):
    """Permet de voir les inscrits directement depuis la fiche événement."""
    model = Inscription
    extra = 0
    readonly_fields = ["date_inscription", "date_confirmation", "token_confirmation"]
    fields = ["nom", "prenoms", "telephone1", "ville", "email", "statut", "date_inscription", "date_confirmation"]


@admin.register(Evenement)
class EvenementAdmin(admin.ModelAdmin):
    list_display = ["titre", "organisateur", "date_debut", "date_fin", "lieu", "places_totales", "nombre_inscrits", "places_restantes"]
    list_filter = ["date_debut", "organisateur"]
    search_fields = ["titre", "lieu", "organisateur__username", "organisateur__email"]
    inlines = [InscriptionInline]
    ordering = ["date_debut"]


@admin.register(Inscription)
class InscriptionAdmin(admin.ModelAdmin):
    list_display = ["nom", "prenoms", "email", "telephone1", "ville", "evenement", "statut", "date_inscription"]
    list_filter = ["statut", "evenement"]
    search_fields = ["nom", "prenoms", "email", "telephone1", "ville"]
    readonly_fields = ["date_inscription", "token_confirmation"]


# ---------------------------------------------------------------------------
# Admin "Organisateurs" — vue personnalisée du modèle User pour gérer
# rapidement l'activation/désactivation des comptes organisateurs.
# ---------------------------------------------------------------------------

class OrganisateurAdmin(DjangoUserAdmin):
    """Remplace l'admin User standard pour mettre en avant les informations
    utiles à la gestion des organisateurs : statut actif/inactif et nombre
    d'événements créés.

    Tout nouveau compte est créé INACTIF par défaut (voir
    OrganisateurCreationForm.save) — l'accès à l'espace organisateur n'est
    débloqué qu'après activation manuelle ici, une fois le paiement reçu
    en direct (hors application)."""

    list_display = [
        "username", "email", "nombre_evenements_organises",
        "statut_compte", "date_joined", "is_active",
    ]
    list_filter = ["is_active", "is_staff", "date_joined"]
    search_fields = ["username", "email"]
    ordering = ["-date_joined"]
    actions = ["activer_comptes", "desactiver_comptes"]

    def get_queryset(self, request):
        # Précalcule le nombre d'événements par utilisateur pour éviter une
        # requête supplémentaire par ligne affichée dans la liste.
        return super().get_queryset(request).annotate(_nb_evenements=Count("evenements"))

    @admin.display(description="Événements créés", ordering="_nb_evenements")
    def nombre_evenements_organises(self, user):
        return user._nb_evenements

    @admin.display(description="Statut", ordering="is_active")
    def statut_compte(self, user):
        if user.is_active:
            return format_html('<span style="color: #198754; font-weight: bold;">{}</span>', "● Actif")
        return format_html('<span style="color: #dc3545; font-weight: bold;">{}</span>', "● En attente / désactivé")

    @admin.action(description="✅ Activer les comptes sélectionnés (après paiement reçu)")
    def activer_comptes(self, request, queryset):
        nombre = queryset.update(is_active=True)
        self.message_user(request, f"{nombre} compte(s) activé(s). Ces organisateurs peuvent maintenant se connecter.")

    @admin.action(description="🚫 Désactiver les comptes sélectionnés")
    def desactiver_comptes(self, request, queryset):
        nombre = queryset.update(is_active=False)
        self.message_user(request, f"{nombre} compte(s) désactivé(s). Leurs événements ne sont plus visibles publiquement.")


admin.site.unregister(User)
admin.site.register(User, OrganisateurAdmin)


# ---------------------------------------------------------------------------
# Paiements — activation/désactivation des moyens de paiement, comptes de
# réception, réglages d'abonnement, et validation des preuves mobile money.
# ---------------------------------------------------------------------------

@admin.register(MoyenPaiement)
class MoyenPaiementAdmin(admin.ModelAdmin):
    """Interrupteur global par moyen de paiement : si désactivé ici, il
    disparaît de tout le site (abonnements ET inscriptions), même si un
    organisateur l'a activé de son côté."""
    list_display = ["code", "actif"]
    list_editable = ["actif"]


@admin.register(CompteReception)
class CompteReceptionAdmin(admin.ModelAdmin):
    list_display = ["moyen_paiement", "proprietaire", "numero_reception", "nom_beneficiaire", "actif"]
    list_filter = ["moyen_paiement", "actif"]
    search_fields = ["numero_reception", "nom_beneficiaire", "proprietaire__username"]


@admin.register(ConfigurationPlateforme)
class ConfigurationPlateformeAdmin(admin.ModelAdmin):
    """Réglages de l'abonnement organisateur (montant, durée) — singleton,
    modifiable sans redéployer le code."""
    list_display = ["montant_abonnement", "duree_abonnement_jours"]

    def has_add_permission(self, request):
        # Singleton : on ne crée jamais de deuxième ligne depuis l'admin.
        return not ConfigurationPlateforme.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(Abonnement)
class AbonnementAdmin(admin.ModelAdmin):
    list_display = ["organisateur", "montant", "date_debut", "date_fin", "est_actif"]
    list_filter = ["organisateur"]
    search_fields = ["organisateur__username", "organisateur__email"]
    readonly_fields = ["date_creation"]

    @admin.display(boolean=True, description="Actif")
    def est_actif(self, abonnement):
        return abonnement.est_actif


@admin.register(Paiement)
class PaiementAdmin(admin.ModelAdmin):
    """Vue centrale de tous les paiements — c'est ici que l'administrateur
    valide les preuves mobile money des ABONNEMENTS (les preuves
    d'INSCRIPTION sont elles validées par l'organisateur concerné, depuis
    son propre espace, pour éviter qu'un abonné puisse voir les paiements
    des autres)."""

    list_display = [
        "id", "type_paiement", "moyen_paiement", "montant", "statut",
        "payeur", "beneficiaire", "date_creation", "apercu_preuve",
    ]
    list_filter = ["type_paiement", "statut", "moyen_paiement"]
    search_fields = ["payeur__username", "beneficiaire__username", "numero_expediteur", "cinetpay_transaction_id"]
    readonly_fields = ["date_creation", "date_validation", "apercu_preuve"]
    actions = ["valider_paiements_selectionnes", "refuser_paiements_selectionnes"]

    @admin.display(description="Preuve")
    def apercu_preuve(self, paiement):
        if not paiement.preuve_paiement:
            return "—"
        return format_html('<a href="{0}" target="_blank"><img src="{0}" style="max-height:60px;"/></a>', paiement.preuve_paiement.url)

    @admin.action(description="✅ Valider les paiements sélectionnés (preuve vérifiée)")
    def valider_paiements_selectionnes(self, request, queryset):
        nombre = 0
        for paiement in queryset.filter(statut=Paiement.Statut.EN_ATTENTE_VALIDATION):
            paiement.valider(valide_par=request.user)
            _notifier_paiement_traite(paiement)
            nombre += 1
        self.message_user(request, f"{nombre} paiement(s) validé(s) et notifié(s) par email.")

    @admin.action(description="🚫 Refuser les paiements sélectionnés")
    def refuser_paiements_selectionnes(self, request, queryset):
        nombre = 0
        for paiement in queryset.filter(statut=Paiement.Statut.EN_ATTENTE_VALIDATION):
            paiement.refuser(motif="Preuve non conforme (vérifiez le montant et le numéro).", valide_par=request.user)
            _notifier_paiement_traite(paiement)
            nombre += 1
        self.message_user(request, f"{nombre} paiement(s) refusé(s) et notifié(s) par email.")


# ---------------------------------------------------------------------------
# Publications
# ---------------------------------------------------------------------------

class PublicationMediaInline(admin.TabularInline):
    model = PublicationMedia
    extra = 0
    fields = ["type_media", "fichier", "legende", "ordre"]


@admin.register(Publication)
class PublicationAdmin(admin.ModelAdmin):
    list_display = ["__str__", "organisateur", "evenement", "date_creation"]
    list_filter = ["organisateur"]
    search_fields = ["texte", "organisateur__username"]
    inlines = [PublicationMediaInline]
