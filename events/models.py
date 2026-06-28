



import secrets
from datetime import timedelta

from django.db import models
from django.conf import settings
from django.core.exceptions import ValidationError
from django.utils import timezone


class EvenementQuerySet(models.QuerySet):
    def publics(self):
        """Ne renvoie que les événements d'organisateurs dont le compte est actif.
        Utilisé pour tout ce qui est visible par les visiteurs (liste, détail,
        formulaire d'inscription) — un organisateur désactivé voit ses
        événements automatiquement masqués du site public."""
        return self.filter(organisateur__is_active=True)


class Evenement(models.Model):
    """Un événement, créé et géré par un organisateur (compte authentifié)."""

    organisateur = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="evenements",
        verbose_name="Organisateur",
    )

    
    titre = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    date_debut = models.DateTimeField(verbose_name="Date de début")
    date_fin = models.DateTimeField(verbose_name="Date de fin")
    lieu = models.CharField(max_length=255)
    places_totales = models.PositiveIntegerField(verbose_name="Nombre de places")
    date_creation = models.DateTimeField(auto_now_add=True)

    objects = EvenementQuerySet.as_manager()

    class Meta:
        ordering = ["date_debut"]
        verbose_name = "Événement"
        verbose_name_plural = "Événements"
        constraints = [
            models.CheckConstraint(
                condition=models.Q(date_fin__gte=models.F("date_debut")),
                name="date_fin_apres_date_debut",
            )
        ]

    def __str__(self):
        return f"{self.titre} ({self.organisateur})"

    @property
    def nombre_inscrits(self):
        """Ne compte que les inscriptions confirmées (double opt-in validé)."""
        return self.inscriptions.filter(statut=Inscription.Statut.CONFIRMEE).count()

    @property
    def places_restantes(self):
        return max(self.places_totales - self.nombre_inscrits, 0)

    @property
    def est_complet(self):
        return self.places_restantes <= 0

    @property
    def duree_en_jours(self):
        """Nombre de jours que dure l'événement (1 si même jour)."""
        return (self.date_fin.date() - self.date_debut.date()).days + 1

    @property
    def sur_un_seul_jour(self):
        return self.date_debut.date() == self.date_fin.date()


def generer_token():
    """Génère un token unique et imprévisible pour le lien de confirmation par email."""
    return secrets.token_urlsafe(32)


def expiration_par_defaut():
    return timezone.now() + timedelta(hours=48)


class Inscription(models.Model):
    """Inscription d'une personne à un événement, soumise à confirmation par email
    (double opt-in) avant d'être définitivement validée."""

    class Statut(models.TextChoices):
        EN_ATTENTE = "EN_ATTENTE", "En attente de confirmation"
        CONFIRMEE = "CONFIRMEE", "Confirmée"
        EXPIREE = "EXPIREE", "Expirée"

    evenement = models.ForeignKey(
        Evenement,
        on_delete=models.CASCADE,
        related_name="inscriptions",
    )
    nom = models.CharField(max_length=150, verbose_name="Nom")
    prenoms = models.CharField(max_length=200, verbose_name="Prénoms")
    telephone1 = models.CharField(max_length=30, verbose_name="Téléphone")
    ville = models.CharField(max_length=150, verbose_name="Ville")
    email = models.EmailField(verbose_name="Adresse email")

    statut = models.CharField(
        max_length=12,
        choices=Statut.choices,
        default=Statut.EN_ATTENTE,
    )
    token_confirmation = models.CharField(max_length=64, unique=True, default=generer_token, editable=False)
    date_inscription = models.DateTimeField(auto_now_add=True)
    date_expiration = models.DateTimeField(default=expiration_par_defaut)
    date_confirmation = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-date_inscription"]
        verbose_name = "Inscription"
        verbose_name_plural = "Inscriptions"
        constraints = [
            # Empêche un même email d'avoir deux inscriptions actives (en attente
            # ou confirmées) pour le même événement. Les inscriptions expirées
            # ne comptent pas, ce qui permet de retenter après expiration.
            models.UniqueConstraint(
                fields=["evenement", "email"],
                condition=models.Q(statut__in=["EN_ATTENTE", "CONFIRMEE"]),
                name="unique_email_actif_par_evenement",
            )
        ]

    def __str__(self):
        return f"{self.prenoms} {self.nom} ({self.email}) -> {self.evenement} [{self.statut}]"

    @property
    def nom_complet(self):
        return f"{self.prenoms} {self.nom}"

    @property
    def est_expiree(self):
        return self.statut == self.Statut.EN_ATTENTE and timezone.now() > self.date_expiration

    def confirmer(self):
        """Valide l'inscription suite au clic sur le lien reçu par email.
        Retourne True si la confirmation a réussi, False si refusée (expirée,
        événement complet, ou organisateur désactivé entre-temps)."""
        if self.statut != self.Statut.EN_ATTENTE:
            return False
        if self.est_expiree:
            self.statut = self.Statut.EXPIREE
            self.save(update_fields=["statut"])
            return False
        if not self.evenement.organisateur.is_active:
            return False
        if self.evenement.est_complet:
            return False

        self.statut = self.Statut.CONFIRMEE
        self.date_confirmation = timezone.now()
        self.save(update_fields=["statut", "date_confirmation"])
        return True

    def clean(self):
        """Sécurité supplémentaire au niveau du modèle (en plus de la vue)."""
        if self.evenement_id and not self.pk and self.evenement.est_complet:
            raise ValidationError("Cet événement est complet, plus de places disponibles.")






