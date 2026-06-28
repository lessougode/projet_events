from django.contrib import admin
from django.contrib.auth import get_user_model
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin
from django.db.models import Count
from django.utils.html import format_html

from .models import Evenement, Inscription

User = get_user_model()


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
