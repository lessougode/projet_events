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

    # --- Paiement (optionnel) ---------------------------------------------
    # Le paiement est facultatif : un organisateur peut très bien créer un
    # événement/formation gratuit (est_payant=False, comportement identique
    # à avant) ou un événement payant, auquel cas l'inscription ne devient
    # CONFIRMEE qu'après validation du paiement (voir Inscription).
    est_payant = models.BooleanField(
        default=False,
        verbose_name="Événement/formation payant(e)",
        help_text="Si coché, les participants doivent régler un paiement avant que leur inscription soit confirmée.",
    )
    prix = models.DecimalField(
        max_digits=10, decimal_places=0, null=True, blank=True,
        verbose_name="Prix",
        help_text="Montant à régler par participant (en XOF). Requis si l'événement est payant.",
    )
    devise = models.CharField(max_length=3, default="XOF", verbose_name="Devise")

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

    def clean(self):
        if self.est_payant and not self.prix:
            raise ValidationError({"prix": "Indiquez un prix : l'événement est marqué comme payant."})

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
        EN_ATTENTE = "EN_ATTENTE", "En attente de confirmation d'email"
        EMAIL_CONFIRME = "EMAIL_CONFIRME", "Email confirmé, en attente de paiement"
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
        max_length=14,
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
        return self.statut in (self.Statut.EN_ATTENTE, self.Statut.EMAIL_CONFIRME) and timezone.now() > self.date_expiration

    @property
    def en_attente_paiement(self):
        return self.statut == self.Statut.EMAIL_CONFIRME

    def confirmer(self):
        """Valide l'inscription suite au clic sur le lien reçu par email.

        Si l'événement est gratuit : l'inscription passe directement à
        CONFIRMEE (comportement historique).
        Si l'événement est payant : l'inscription passe seulement à
        EMAIL_CONFIRME, en attente du paiement (voir valider_paiement).

        Retourne True si l'étape a réussi, False si refusée (expirée,
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

        if self.evenement.est_payant:
            # On laisse un nouveau délai de 48h pour effectuer le paiement.
            self.statut = self.Statut.EMAIL_CONFIRME
            self.date_expiration = expiration_par_defaut()
            self.save(update_fields=["statut", "date_expiration"])
            return True

        self.statut = self.Statut.CONFIRMEE
        self.date_confirmation = timezone.now()
        self.save(update_fields=["statut", "date_confirmation"])
        return True

    def valider_paiement(self):
        """Confirme définitivement l'inscription après validation du paiement
        (preuve mobile money validée par l'organisateur/admin, ou paiement
        CinetPay confirmé auprès de l'API). Retourne True si la confirmation
        a réussi."""
        if self.statut != self.Statut.EMAIL_CONFIRME:
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


# ---------------------------------------------------------------------------
# Paiements
#
# Deux usages distincts partagent la même infrastructure :
#   1) ABONNEMENT   : un organisateur (= commerçant) paie la plateforme pour
#                      pouvoir utiliser l'application (créer des événements).
#   2) INSCRIPTION  : un participant paie l'organisateur pour participer à
#                      un événement/une formation payant(e).
#
# Deux familles de moyens de paiement :
#   - Mobile Money "direct" (Orange Money, MTN MoMo, Moov Money) : aucune API
#     tierce (pas de Twilio, pas d'agrégateur). Le payeur envoie l'argent
#     directement au numéro affiché puis dépose une CAPTURE D'ÉCRAN de la
#     transaction comme preuve. Le bénéficiaire (organisateur pour une
#     inscription, administrateur pour un abonnement) valide manuellement en
#     comparant la preuve à ce qu'il a reçu ; un email de confirmation est
#     envoyé au payeur une fois le paiement validé.
#   - CinetPay : paiement 100% en ligne (carte, mobile money agrégé) via
#     l'API CinetPay (v2/payment puis vérification systématique côté
#     serveur via v2/payment/check — on ne fait jamais confiance à la seule
#     URL de retour, cf. commentaire historique dans views.py).
# ---------------------------------------------------------------------------

class MoyenPaiement(models.Model):
    """Catalogue global des moyens de paiement gérés par la plateforme.

    Activable/désactivable par l'administrateur : si un moyen est désactivé
    ici, il disparaît de partout (abonnements ET inscriptions), même si un
    organisateur l'a lui-même activé dans sa configuration."""

    class Code(models.TextChoices):
        ORANGE_MONEY = "ORANGE_MONEY", "Orange Money"
        MTN_MOMO = "MTN_MOMO", "MTN Mobile Money"
        MOOV_MONEY = "MOOV_MONEY", "Moov Money"
        WAVE = "WAVE", "Wave"
        CINETPAY = "CINETPAY", "CinetPay (carte bancaire / mobile money agrégé)"

    # Les moyens "mobile money direct" nécessitent une preuve de paiement
    # (capture d'écran) et une validation manuelle. CinetPay est entièrement
    # automatisé via API.
    MOYENS_MOBILE_MONEY_DIRECT = [Code.ORANGE_MONEY, Code.MTN_MOMO, Code.MOOV_MONEY, Code.WAVE]

    code = models.CharField(max_length=20, choices=Code.choices, unique=True)
    actif = models.BooleanField(
        default=True,
        verbose_name="Actif sur la plateforme",
        help_text="Si décoché, ce moyen de paiement est indisponible partout, même s'il est activé par un organisateur.",
    )

    class Meta:
        verbose_name = "Moyen de paiement"
        verbose_name_plural = "Moyens de paiement (plateforme)"
        ordering = ["code"]

    def __str__(self):
        return self.get_code_display()

    @property
    def est_mobile_money_direct(self):
        return self.code in self.MOYENS_MOBILE_MONEY_DIRECT

    @property
    def est_cinetpay(self):
        return self.code == self.Code.CINETPAY


class CompteReceptionQuerySet(models.QuerySet):
    def disponibles(self):
        """Comptes de réception réellement utilisables : actifs côté
        propriétaire ET actifs côté plateforme."""
        return self.filter(actif=True, moyen_paiement__actif=True)


class CompteReception(models.Model):
    """Configuration d'un moyen de paiement pour un bénéficiaire donné.

    proprietaire = None  -> compte de la PLATEFORME (encaisse les
                             abonnements des organisateurs).
    proprietaire = <User> -> compte de cet ORGANISATEUR (encaisse les
                             inscriptions payantes de ses propres
                             événements/formations).

    Chaque organisateur choisit librement quels moyens il active, en
    fonction de ce qu'il possède réellement (un numéro Orange Money, un
    numéro MTN MoMo, un compte CinetPay...). L'administrateur fait de même
    pour le compte plateforme."""

    proprietaire = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="comptes_reception",
        null=True, blank=True,
        verbose_name="Organisateur",
        help_text="Laisser vide pour le compte de la plateforme (réception des abonnements).",
    )
    moyen_paiement = models.ForeignKey(MoyenPaiement, on_delete=models.CASCADE, related_name="comptes_reception")
    numero_reception = models.CharField(
        max_length=30, blank=True,
        verbose_name="Numéro de réception",
        help_text="Numéro mobile money qui recevra les paiements. Inutile pour CinetPay.",
    )
    nom_beneficiaire = models.CharField(
        max_length=150, blank=True,
        verbose_name="Nom du titulaire",
        help_text="Nom affiché au payeur pour qu'il vérifie le destinataire avant d'envoyer l'argent.",
    )
    actif = models.BooleanField(default=True, verbose_name="Activé")

    objects = CompteReceptionQuerySet.as_manager()

    class Meta:
        verbose_name = "Compte de réception"
        verbose_name_plural = "Comptes de réception"
        constraints = [
            models.UniqueConstraint(fields=["proprietaire", "moyen_paiement"], name="unique_moyen_par_proprietaire")
        ]
        ordering = ["moyen_paiement__code"]

    def __str__(self):
        qui = self.proprietaire.username if self.proprietaire_id else "Plateforme"
        return f"{self.moyen_paiement} — {qui}"

    def clean(self):
        if self.moyen_paiement_id and self.moyen_paiement.est_mobile_money_direct and not self.numero_reception:
            raise ValidationError({"numero_reception": "Numéro requis pour un moyen de paiement mobile money."})


def moyens_disponibles_pour(proprietaire):
    """Retourne les CompteReception réellement utilisables pour un
    bénéficiaire donné (organisateur, ou None pour la plateforme) :
    activés par le bénéficiaire ET activés par l'administrateur."""
    return CompteReception.objects.disponibles().filter(proprietaire=proprietaire).select_related("moyen_paiement")


class ConfigurationPlateforme(models.Model):
    """Réglages globaux de l'abonnement organisateur (singleton).
    Modifiable depuis /admin/ sans avoir besoin de redéployer le code."""

    montant_abonnement = models.DecimalField(
        max_digits=10, decimal_places=0, default=5000,
        verbose_name="Montant de l'abonnement (XOF)",
    )
    duree_abonnement_jours = models.PositiveIntegerField(
        default=30,
        verbose_name="Durée de l'abonnement (jours)",
    )

    class Meta:
        verbose_name = "Configuration de la plateforme"
        verbose_name_plural = "Configuration de la plateforme"

    def __str__(self):
        return "Configuration de la plateforme"

    def save(self, *args, **kwargs):
        self.pk = 1  # Singleton : toujours la même ligne
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        pass  # On ne supprime jamais la configuration

    @classmethod
    def charger(cls):
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj


def chemin_preuve_paiement(instance, filename):
    return f"preuves_paiement/{instance.type_paiement.lower()}/{filename}"


class Paiement(models.Model):
    """Une transaction de paiement, qu'il s'agisse d'un abonnement
    organisateur ou d'une inscription payante à un événement/formation."""

    class Type(models.TextChoices):
        ABONNEMENT = "ABONNEMENT", "Abonnement organisateur"
        INSCRIPTION = "INSCRIPTION", "Inscription à un événement/formation"

    class Statut(models.TextChoices):
        EN_ATTENTE = "EN_ATTENTE", "En attente (moyen non encore choisi)"
        EN_ATTENTE_VALIDATION = "EN_ATTENTE_VALIDATION", "Preuve envoyée, en attente de validation"
        EN_ATTENTE_CINETPAY = "EN_ATTENTE_CINETPAY", "En attente de retour CinetPay"
        VALIDE = "VALIDE", "Payé et validé"
        REFUSE = "REFUSE", "Refusé"
        ECHEC = "ECHEC", "Échec / annulé"

    type_paiement = models.CharField(max_length=15, choices=Type.choices)

    # Sens du paiement : qui paie, qui reçoit.
    payeur = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL, null=True, blank=True,
        related_name="paiements_effectues",
        help_text="Rempli pour un abonnement (l'organisateur qui paie). Vide pour une inscription (visiteur non authentifié).",
    )
    beneficiaire = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL, null=True, blank=True,
        related_name="paiements_recus",
        help_text="Organisateur qui reçoit le paiement d'inscription. Vide pour un abonnement (reçu par la plateforme).",
    )
    inscription = models.OneToOneField(
        Inscription, on_delete=models.CASCADE, null=True, blank=True, related_name="paiement",
    )
    abonnement = models.OneToOneField(
        "Abonnement", on_delete=models.CASCADE, null=True, blank=True, related_name="paiement",
    )

    moyen_paiement = models.ForeignKey(MoyenPaiement, on_delete=models.PROTECT, related_name="paiements")
    montant = models.DecimalField(max_digits=10, decimal_places=0)
    devise = models.CharField(max_length=3, default="XOF")

    statut = models.CharField(max_length=25, choices=Statut.choices, default=Statut.EN_ATTENTE)

    # --- Mobile money direct : preuve + validation manuelle ---
    preuve_paiement = models.ImageField(upload_to=chemin_preuve_paiement, null=True, blank=True, verbose_name="Capture d'écran du paiement")
    numero_expediteur = models.CharField(max_length=30, blank=True, verbose_name="Numéro utilisé pour payer")
    reference_saisie = models.CharField(max_length=100, blank=True, verbose_name="Référence de la transaction (facultatif)")
    valide_par = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="paiements_valides",
    )
    date_validation = models.DateTimeField(null=True, blank=True)
    motif_refus = models.CharField(max_length=255, blank=True)

    # --- CinetPay ---
    cinetpay_transaction_id = models.CharField(max_length=100, blank=True, unique=False, db_index=True)
    cinetpay_payment_token = models.CharField(max_length=255, blank=True)

    date_creation = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Paiement"
        verbose_name_plural = "Paiements"
        ordering = ["-date_creation"]
        constraints = [
            models.CheckConstraint(
                condition=(
                    models.Q(type_paiement="ABONNEMENT", inscription__isnull=True)
                    | models.Q(type_paiement="INSCRIPTION", abonnement__isnull=True)
                ),
                name="paiement_lie_a_un_seul_objet",
            )
        ]

    def __str__(self):
        cible = self.inscription or self.abonnement
        return f"Paiement {self.get_type_paiement_display()} — {self.montant} {self.devise} — {self.get_statut_display()} ({cible})"

    @property
    def en_attente_de_validation_manuelle(self):
        return self.moyen_paiement.est_mobile_money_direct and self.statut == self.Statut.EN_ATTENTE_VALIDATION

    def save(self, *args, **kwargs):
        """Filet de sécurité : si le statut passe à VALIDE — que ce soit via
        `.valider()` ou via une modification manuelle du champ dans
        l'admin — l'inscription/l'abonnement lié est confirmé automatiquement.
        Sans ça, un changement de statut fait à la main dans le formulaire
        d'admin (au lieu de l'action groupée "Valider les paiements
        sélectionnés") laisse le compte organisateur inactif malgré un
        statut affiché "Payé et validé"."""
        devient_valide = False
        if self.pk:
            ancien_statut = Paiement.objects.filter(pk=self.pk).values_list("statut", flat=True).first()
            devient_valide = ancien_statut != self.Statut.VALIDE and self.statut == self.Statut.VALIDE
        if devient_valide and not self.date_validation:
            self.date_validation = timezone.now()

        super().save(*args, **kwargs)

        if devient_valide:
            if self.inscription_id:
                self.inscription.valider_paiement()
            elif self.abonnement_id and not self.abonnement.date_debut:
                self.abonnement.activer()

    def valider(self, valide_par=None):
        """Marque le paiement comme validé, confirme l'objet lié
        (inscription ou abonnement) et renvoie True si tout s'est bien passé."""
        if self.statut == self.Statut.VALIDE:
            return True
        self.statut = self.Statut.VALIDE
        self.valide_par = valide_par
        self.save()
        return True

    def refuser(self, motif="", valide_par=None):
        self.statut = self.Statut.REFUSE
        self.motif_refus = motif
        self.valide_par = valide_par
        self.date_validation = timezone.now()
        self.save(update_fields=["statut", "motif_refus", "valide_par", "date_validation"])


class AbonnementQuerySet(models.QuerySet):
    def actifs(self):
        return self.filter(date_fin__gte=timezone.now())


class Abonnement(models.Model):
    """Une période d'abonnement payée par un organisateur (= commerçant)
    pour avoir le droit d'utiliser la plateforme. À l'activation, débloque
    le compte organisateur (is_active=True)."""

    organisateur = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="abonnements",
    )
    montant = models.DecimalField(max_digits=10, decimal_places=0)
    date_creation = models.DateTimeField(auto_now_add=True)
    date_debut = models.DateTimeField(null=True, blank=True)
    date_fin = models.DateTimeField(null=True, blank=True)

    objects = AbonnementQuerySet.as_manager()

    class Meta:
        verbose_name = "Abonnement"
        verbose_name_plural = "Abonnements"
        ordering = ["-date_creation"]

    def __str__(self):
        return f"Abonnement {self.organisateur} ({self.date_debut:%d/%m/%Y} → {self.date_fin:%d/%m/%Y})" if self.date_debut else f"Abonnement {self.organisateur} (en attente de paiement)"

    @property
    def est_actif(self):
        return bool(self.date_fin) and self.date_fin >= timezone.now()

    def activer(self):
        """Active l'abonnement (paiement validé) : calcule la période,
        prolonge à partir d'un abonnement en cours s'il y en a un, et
        réactive le compte organisateur."""
        config = ConfigurationPlateforme.charger()
        duree = timedelta(days=config.duree_abonnement_jours)

        dernier_actif = (
            Abonnement.objects.filter(organisateur=self.organisateur)
            .exclude(pk=self.pk)
            .actifs()
            .order_by("-date_fin")
            .first()
        )
        depart = dernier_actif.date_fin if dernier_actif else timezone.now()

        self.date_debut = timezone.now()
        self.date_fin = depart + duree
        self.save(update_fields=["date_debut", "date_fin"])

        self.organisateur.is_active = True
        self.organisateur.save(update_fields=["is_active"])


# ---------------------------------------------------------------------------
# Publications (texte + photos + vidéos), publiées par un organisateur.
# ---------------------------------------------------------------------------

class Publication(models.Model):
    """Une publication d'un organisateur : texte libre pouvant être
    accompagné de plusieurs photos et/ou vidéos (voir PublicationMedia)."""

    organisateur = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="publications",
    )
    evenement = models.ForeignKey(
        Evenement, on_delete=models.SET_NULL, null=True, blank=True, related_name="publications",
        verbose_name="Événement lié (facultatif)",
    )
    texte = models.TextField(blank=True, verbose_name="Texte")
    date_creation = models.DateTimeField(auto_now_add=True)
    date_modification = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Publication"
        verbose_name_plural = "Publications"
        ordering = ["-date_creation"]

    def __str__(self):
        apercu = (self.texte[:50] + "…") if len(self.texte) > 50 else self.texte
        return apercu or f"Publication #{self.pk} de {self.organisateur}"

    def clean(self):
        # Une publication doit contenir au moins du texte OU un média
        # (vérifié aussi côté formulaire ; sécurité supplémentaire ici).
        if not self.texte and self.pk and not self.medias.exists():
            raise ValidationError("Une publication doit contenir au moins du texte, une photo ou une vidéo.")


EXTENSIONS_PHOTO = ["jpg", "jpeg", "png", "webp", "gif"]
EXTENSIONS_VIDEO = ["mp4", "webm", "mov", "m4v"]


def chemin_media_publication(instance, filename):
    return f"publications/{instance.publication.organisateur_id}/{filename}"


class PublicationMedia(models.Model):
    """Une photo ou une vidéo attachée à une publication."""

    class TypeMedia(models.TextChoices):
        PHOTO = "PHOTO", "Photo"
        VIDEO = "VIDEO", "Vidéo"

    publication = models.ForeignKey(Publication, on_delete=models.CASCADE, related_name="medias")
    type_media = models.CharField(max_length=5, choices=TypeMedia.choices)
    fichier = models.FileField(upload_to=chemin_media_publication)
    legende = models.CharField(max_length=200, blank=True)
    ordre = models.PositiveIntegerField(default=0)

    class Meta:
        verbose_name = "Média de publication"
        verbose_name_plural = "Médias de publication"
        ordering = ["ordre", "id"]

    def __str__(self):
        return f"{self.get_type_media_display()} — {self.publication}"

    def clean(self):
        if not self.fichier:
            return
        extension = self.fichier.name.rsplit(".", 1)[-1].lower()
        if self.type_media == self.TypeMedia.PHOTO and extension not in EXTENSIONS_PHOTO:
            raise ValidationError({"fichier": f"Extension d'image non autorisée : .{extension}"})
        if self.type_media == self.TypeMedia.VIDEO and extension not in EXTENSIONS_VIDEO:
            raise ValidationError({"fichier": f"Extension de vidéo non autorisée : .{extension}"})