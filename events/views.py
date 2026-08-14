from asyncio.log import logger
from functools import wraps

from django import forms
from django.contrib.auth import get_user_model
from django.shortcuts import render, redirect, get_object_or_404
from django.utils import timezone
from utils import send_email_with_template

from django.core.mail import send_mail

from django.conf import settings
from django.db import IntegrityError, transaction
from django.contrib import messages
from django.contrib.auth import logout
from django.contrib.auth.decorators import login_required
from django.http import FileResponse, Http404
from django.urls import reverse

import secrets

from django.forms import modelformset_factory
from django.views.decorators.http import require_POST

from .models import (
    Evenement, Inscription, MoyenPaiement, CompteReception, Paiement,
    ConfigurationPlateforme, Abonnement, Publication, PublicationMedia,
    moyens_disponibles_pour, EXTENSIONS_VIDEO,
)
from .forms import (
    InscriptionForm, OrganisateurCreationForm, EvenementForm,
    CompteReceptionForm, PreuvePaiementForm, PublicationForm,
)
from .excel_export import regenerer_excel_evenement, chemin_fichier_excel
from . import cinetpay

User = get_user_model()


def organisateur_required(vue):
    """Comme @login_required, mais vérifie en plus que le compte est toujours
    actif à chaque requête. Une session déjà ouverte au moment où un compte
    est désactivé depuis l'admin est immédiatement coupée au prochain accès
    à l'espace organisateur (Django ne fait pas cette vérification par
    défaut : is_active ne bloque que la connexion, pas une session existante)."""
    @wraps(vue)
    @login_required
    def vue_protegee(request, *args, **kwargs):
        if not request.user.is_active:
            logout(request)
            messages.error(request, "Votre compte a été désactivé. Contactez l'administrateur du site.")
            return redirect("connexion")
        return vue(request, *args, **kwargs)
    return vue_protegee


# ---------------------------------------------------------------------------
# Espace public (visiteurs, sans authentification)
# ---------------------------------------------------------------------------

def liste_evenements(request):
    """Affiche tous les événements non terminés, toutes organisations confondues,
    triés par date de début. Les événements d'un organisateur désactivé
    n'apparaissent pas (voir EvenementQuerySet.publics)."""
    evenements = Evenement.objects.publics().filter(date_fin__gte=timezone.now())
    return render(request, "events/liste.html", {"evenements": evenements})


def detail_evenement(request, pk):
    """Affiche le détail d'un événement (page publique).
    404 si l'organisateur a été désactivé, comme si l'événement n'existait plus."""
    evenement = get_object_or_404(Evenement.objects.publics(), pk=pk)
    return render(request, "events/detail.html", {"evenement": evenement})


def inscription_evenement(request, pk):
    """Formulaire d'inscription à un événement.

    L'inscription créée est en statut EN_ATTENTE et ne décompte aucune place.
    Un email contenant un lien de confirmation (valable 48h) est envoyé ;
    ce n'est qu'au clic sur ce lien que l'inscription devient CONFIRMEE,
    qu'une place est décomptée, et que la personne est ajoutée au fichier
    Excel des inscrits de l'événement.
    """
    evenement = get_object_or_404(Evenement.objects.publics(), pk=pk)

    # RG-02 : pas de nouvelle inscription possible si l'événement est déjà complet
    # (en places confirmées — voir Evenement.nombre_inscrits)
    if evenement.est_complet:
        return render(request, "events/complet.html", {"evenement": evenement})

    if request.method == "POST":
        form = InscriptionForm(request.POST)
        if form.is_valid():
            inscription = form.save(commit=False)
            inscription.evenement = evenement
            try:
                with transaction.atomic():
                    inscription.save()
            except IntegrityError:
                # RG-03 : un même email ne peut avoir deux inscriptions actives
                # (en attente ou confirmée) pour le même événement
                form.add_error("email", "Cet email a déjà une inscription en cours pour cet événement.")
            # else:
            #     _envoyer_email_validation(request, inscription)
            #     return redirect("verifier_votre_email", pk=evenement.pk)


            else:
                try:
                    _envoyer_email_validation(request, inscription)
                    print("✅ EMAIL ENVOYE A", inscription.email)
                except Exception as e:
                    import traceback
                    traceback.print_exc()
                return redirect("verifier_votre_email", pk=evenement.pk)
    else:
        form = InscriptionForm()

    return render(
        request,
        "events/inscription_form.html",
        {"form": form, "evenement": evenement},
    )


def verifier_votre_email(request, pk):
    """Page affichée juste après le formulaire : invite à consulter sa boîte mail."""
    evenement = get_object_or_404(Evenement, pk=pk)
    return render(request, "events/verifier_email.html", {"evenement": evenement})


def confirmer_inscription(request, token):
    """Traite le clic sur le lien de confirmation reçu par email (double opt-in)."""
    inscription = get_object_or_404(Inscription, token_confirmation=token)
    evenement = inscription.evenement

    if inscription.statut == Inscription.Statut.CONFIRMEE:
        # Lien déjà utilisé : on affiche quand même la confirmation, sans erreur,
        # au cas où la personne aurait cliqué deux fois sur le lien.
        return render(request, "events/confirmation.html", {"evenement": evenement})

    reussite = inscription.confirmer()

    if not reussite:
        return render(request, "events/lien_invalide.html", {"evenement": evenement, "inscription": inscription})

    # Événement payant : l'email est confirmé mais l'inscription n'est pas
    # encore définitive — direction le choix du moyen de paiement.
    if inscription.statut == Inscription.Statut.EMAIL_CONFIRME:
        return redirect("choisir_paiement_inscription", token=token)

    # Source de vérité = base de données ; le fichier Excel est régénéré
    # entièrement à partir des inscriptions confirmées de l'événement.
    regenerer_excel_evenement(evenement)

    return render(request, "events/confirmation.html", {"evenement": evenement})




# token de confirmation : on pourrait utiliser le système de tokens de Django (PasswordResetTokenGenerator)




from django.core.mail import send_mail
from django.conf import settings
from django.urls import reverse


def _envoyer_email_validation(request, inscription):
    evenement = inscription.evenement
    lien_confirmation = request.build_absolute_uri(
        reverse("confirmer_inscription", args=[inscription.token_confirmation])
    )
    context = {
        'prenoms': inscription.prenoms,
        'nom': inscription.nom,
        'evenement': evenement.titre,
        'lien_confirmation': lien_confirmation,
        'delai': "48 heures",
    }

    send_email_with_template(
        subject=f"Confirmez votre inscription : {evenement.titre}",
        template_name="events/email_confirmation.html",
        context=context,
        to_email=[inscription.email],
        from_email=settings.EMAIL_HOST_USER,
    )


# ---------------------------------------------------------------------------
# Paiement visiteur — inscription payante (Mobile Money direct / CinetPay)
#
# Flux : email confirmé (EMAIL_CONFIRME) -> choix du moyen de paiement
# -> soit dépôt d'une preuve (mobile money direct, validée manuellement par
# l'organisateur) soit redirection vers CinetPay -> retour sur le site ->
# vérification réelle du statut auprès de CinetPay -> valider_paiement() si
# réussi.
#
# IMPORTANT : on ne fait jamais confiance aux seuls paramètres de l'URL de
# retour pour valider un paiement (un visiteur malveillant pourrait
# fabriquer une URL de succès sans avoir payé). On revérifie toujours le
# statut réel auprès de CinetPay avant de confirmer quoi que ce soit.
# ---------------------------------------------------------------------------

def _envoyer_email_paiement_confirme(request, inscription):
    """Email envoyé une fois le paiement de l'inscription validé (par
    l'organisateur pour une preuve mobile money, ou automatiquement après
    vérification CinetPay) — l'inscription est alors définitivement CONFIRMEE."""
    evenement = inscription.evenement
    send_email_with_template(
        subject=f"Paiement reçu — inscription confirmée : {evenement.titre}",
        template_name="events/email_paiement_confirme.html",
        context={
            "prenoms": inscription.prenoms, "nom": inscription.nom,
            "evenement": evenement.titre,
        },
        to_email=[inscription.email],
        from_email=settings.EMAIL_HOST_USER,
    )


def _envoyer_email_paiement_refuse(inscription, motif):
    evenement = inscription.evenement
    lien = None  # pas de lien direct : la personne doit recontacter l'organisateur
    send_email_with_template(
        subject=f"Paiement non validé : {evenement.titre}",
        template_name="events/email_paiement_refuse.html",
        context={
            "prenoms": inscription.prenoms, "nom": inscription.nom,
            "evenement": evenement.titre, "motif": motif,
        },
        to_email=[inscription.email],
        from_email=settings.EMAIL_HOST_USER,
    )


def _get_inscription_payante_ou_404(token):
    """Récupère une inscription en attente de paiement à partir de son
    token, ou 404 si le token est invalide ou l'étape déjà dépassée."""
    inscription = get_object_or_404(Inscription, token_confirmation=token)
    if inscription.statut != Inscription.Statut.EMAIL_CONFIRME:
        raise Http404("Cette inscription n'est pas (ou plus) en attente de paiement.")
    return inscription


def choisir_paiement_inscription(request, token):
    """Page publique : le participant choisit un moyen de paiement parmi
    ceux activés par l'organisateur de l'événement (et par l'admin)."""
    inscription = _get_inscription_payante_ou_404(token)
    evenement = inscription.evenement

    if inscription.est_expiree:
        inscription.statut = Inscription.Statut.EXPIREE
        inscription.save(update_fields=["statut"])
        return render(request, "events/lien_invalide.html", {"evenement": evenement, "inscription": inscription})

    comptes = moyens_disponibles_pour(evenement.organisateur)
    return render(request, "events/paiement_choix.html", {
        "evenement": evenement, "inscription": inscription, "comptes": comptes,
    })


def soumettre_preuve_inscription(request, token, compte_id):
    """Dépôt de la preuve de paiement Mobile Money direct pour une inscription."""
    inscription = _get_inscription_payante_ou_404(token)
    evenement = inscription.evenement
    compte = get_object_or_404(
        CompteReception.objects.disponibles(), pk=compte_id, proprietaire=evenement.organisateur,
    )
    if compte.moyen_paiement.est_cinetpay:
        raise Http404("Ce moyen de paiement ne prend pas de preuve manuelle.")

    paiement, _ = Paiement.objects.get_or_create(
        inscription=inscription,
        defaults={
            "type_paiement": Paiement.Type.INSCRIPTION,
            "beneficiaire": evenement.organisateur,
            "montant": evenement.prix,
            "moyen_paiement": compte.moyen_paiement,
        },
    )

    if request.method == "POST":
        form = PreuvePaiementForm(request.POST, request.FILES, instance=paiement)
        if form.is_valid():
            paiement = form.save(commit=False)
            paiement.moyen_paiement = compte.moyen_paiement
            paiement.montant = evenement.prix
            paiement.statut = Paiement.Statut.EN_ATTENTE_VALIDATION
            paiement.save()
            messages.success(request, "Votre preuve de paiement a bien été envoyée.")
            return redirect("paiement_soumis", token=token)
    else:
        form = PreuvePaiementForm(instance=paiement)

    return render(request, "events/paiement_preuve_form.html", {
        "evenement": evenement, "inscription": inscription, "compte": compte, "form": form,
    })


def paiement_soumis(request, token):
    """Page d'attente affichée après le dépôt d'une preuve de paiement :
    invite à patienter pendant la validation manuelle par l'organisateur."""
    inscription = get_object_or_404(Inscription, token_confirmation=token)
    return render(request, "events/paiement_soumis.html", {"inscription": inscription, "evenement": inscription.evenement})


def payer_cinetpay_inscription(request, token, compte_id):
    """Initialise un paiement CinetPay pour une inscription et redirige
    le participant vers la page de paiement CinetPay."""
    inscription = _get_inscription_payante_ou_404(token)
    evenement = inscription.evenement
    compte = get_object_or_404(
        CompteReception.objects.disponibles(), pk=compte_id, proprietaire=evenement.organisateur,
        moyen_paiement__code=MoyenPaiement.Code.CINETPAY,
    )

    paiement, _ = Paiement.objects.get_or_create(
        inscription=inscription,
        defaults={
            "type_paiement": Paiement.Type.INSCRIPTION,
            "beneficiaire": evenement.organisateur,
            "montant": evenement.prix,
            "moyen_paiement": compte.moyen_paiement,
        },
    )
    if not paiement.cinetpay_transaction_id:
        paiement.cinetpay_transaction_id = f"INSCRIPTION-{inscription.pk}-{secrets.token_hex(4)}"
    paiement.moyen_paiement = compte.moyen_paiement
    paiement.montant = evenement.prix
    paiement.statut = Paiement.Statut.EN_ATTENTE_CINETPAY
    paiement.save()

    url_retour = request.build_absolute_uri(reverse("cinetpay_retour_inscription", args=[token]))
    try:
        payment_url = cinetpay.initier_paiement(
            transaction_id=paiement.cinetpay_transaction_id,
            montant=evenement.prix,
            description=f"Inscription : {evenement.titre}",
            url_retour=url_retour,
            client_nom=inscription.nom_complet,
            client_email=inscription.email,
            client_telephone=inscription.telephone1,
        )
    except cinetpay.CinetPayError as exc:
        messages.error(request, f"Paiement CinetPay indisponible pour le moment : {exc}")
        return redirect("choisir_paiement_inscription", token=token)

    return redirect(payment_url)


def cinetpay_retour_inscription(request, token):
    """Retour du navigateur après un paiement CinetPay : on ne fait jamais
    confiance à l'URL, on revérifie le statut réel auprès de CinetPay."""
    inscription = get_object_or_404(Inscription, token_confirmation=token)
    evenement = inscription.evenement
    paiement = getattr(inscription, "paiement", None)

    if not paiement or not paiement.cinetpay_transaction_id:
        raise Http404("Aucun paiement CinetPay associé à cette inscription.")

    try:
        resultat = cinetpay.verifier_transaction(paiement.cinetpay_transaction_id)
    except cinetpay.CinetPayError as exc:
        messages.error(request, f"Impossible de vérifier votre paiement : {exc}")
        return redirect("choisir_paiement_inscription", token=token)

    if resultat["payee"] and inscription.statut == Inscription.Statut.EMAIL_CONFIRME:
        paiement.valider()  # -> déclenche inscription.valider_paiement()
        regenerer_excel_evenement(evenement)
        try:
            _envoyer_email_paiement_confirme(request, inscription)
        except Exception:
            import traceback
            traceback.print_exc()
        return render(request, "events/confirmation.html", {"evenement": evenement})

    if inscription.statut == Inscription.Statut.CONFIRMEE:
        # Retour répété après un premier succès (double clic, retour arrière...)
        return render(request, "events/confirmation.html", {"evenement": evenement})

    paiement.statut = Paiement.Statut.ECHEC
    paiement.save(update_fields=["statut"])
    return render(request, "events/paiement_echec.html", {
        "evenement": evenement, "inscription": inscription, "statut_cinetpay": resultat["statut"],
    })


# Authentification organisateur (inscription libre)
# ---------------------------------------------------------------------------

def inscription_organisateur(request):
    """Permet à un organisateur de créer librement son compte.

    Le compte est créé INACTIF par défaut : l'accès est débloqué
    manuellement par l'administrateur depuis /admin/ une fois le paiement
    reçu en direct (hors application). On ne connecte donc jamais
    automatiquement après cette inscription — un compte inactif ne peut
    de toute façon pas être authentifié par Django."""
    if request.user.is_authenticated:
        return redirect("dashboard_organisateur")

    if request.method == "POST":
        form = OrganisateurCreationForm(request.POST)
        if form.is_valid():
            nouvel_organisateur = form.save()
            # Le compte est inactif : impossible de le connecter (Django
            # bloque l'authentification des comptes is_active=False). On
            # mémorise juste son identifiant en session pour lui permettre
            # de régler son abonnement tout de suite, sans mot de passe.
            request.session["organisateur_abonnement_id"] = nouvel_organisateur.pk
            return redirect("compte_en_attente")
    else:
        form = OrganisateurCreationForm()

    return render(request, "events/inscription_organisateur.html", {"form": form})


def compte_en_attente(request):
    """Page affichée après inscription, tant que le compte n'est pas encore activé."""
    return render(request, "events/compte_en_attente.html")


class RetrouverCompteForm(forms.Form):
    """Un organisateur inactif ne peut pas se connecter (Django bloque
    l'authentification des comptes désactivés) : ce formulaire lui permet
    de se re-identifier par identifiant + email, sans mot de passe, pour
    revenir régler son abonnement."""

    username = forms.CharField(label="Nom d'utilisateur", widget=forms.TextInput(attrs={"class": "form-control"}))
    email = forms.EmailField(label="Adresse email utilisée à l'inscription", widget=forms.EmailInput(attrs={"class": "form-control"}))

    def clean(self):
        cleaned_data = super().clean()
        username = cleaned_data.get("username")
        email = cleaned_data.get("email")
        if username and email:
            try:
                self.organisateur = User.objects.get(username=username, email__iexact=email)
            except User.DoesNotExist:
                raise forms.ValidationError("Aucun compte ne correspond à ces informations.")
        return cleaned_data


def retrouver_compte_abonnement(request):
    """Permet à un organisateur dont le compte est encore inactif (donc
    incapable de se connecter) de revenir régler son abonnement plus tard,
    sans mot de passe."""
    if request.method == "POST":
        form = RetrouverCompteForm(request.POST)
        if form.is_valid():
            request.session["organisateur_abonnement_id"] = form.organisateur.pk
            return redirect("organisateur_abonnement")
    else:
        form = RetrouverCompteForm()
    return render(request, "events/retrouver_compte_abonnement.html", {"form": form})


# ---------------------------------------------------------------------------
# Espace organisateur (authentification obligatoire)
#
# RÈGLE D'ISOLATION MULTI-TENANT — CRITIQUE :
# Chaque vue ci-dessous filtre TOUJOURS les événements par
# `organisateur=request.user`. Jamais de Evenement.objects.get(pk=...) seul,
# car cela permettrait à un organisateur connecté d'accéder aux données
# d'un autre organisateur simplement en devinant/modifiant un ID dans l'URL.
# ---------------------------------------------------------------------------

@organisateur_required
def dashboard_organisateur(request):
    """Liste des événements appartenant à l'organisateur connecté, uniquement."""
    evenements = Evenement.objects.filter(organisateur=request.user)
    return render(request, "events/dashboard.html", {"evenements": evenements})


@organisateur_required
def creer_evenement(request):
    """Création d'un nouvel événement, automatiquement rattaché à l'organisateur connecté."""
    if request.method == "POST":
        form = EvenementForm(request.POST)
        if form.is_valid():
            evenement = form.save(commit=False)
            evenement.organisateur = request.user
            evenement.save()
            messages.success(request, "Événement créé avec succès.")
            return redirect("dashboard_organisateur")
    else:
        form = EvenementForm()

    return render(request, "events/evenement_form.html", {"form": form, "creation": True})


@organisateur_required
def modifier_evenement(request, pk):
    """Modification d'un événement — réservé à son organisateur propriétaire."""
    # Isolation : le filtre organisateur=request.user fait que get_object_or_404
    # renvoie une 404 (et non une 403) si l'événement appartient à quelqu'un
    # d'autre, sans révéler qu'il existe.
    evenement = get_object_or_404(Evenement, pk=pk, organisateur=request.user)

    if request.method == "POST":
        form = EvenementForm(request.POST, instance=evenement)
        if form.is_valid():
            form.save()
            messages.success(request, "Événement mis à jour.")
            return redirect("dashboard_organisateur")
    else:
        form = EvenementForm(instance=evenement)

    return render(request, "events/evenement_form.html", {"form": form, "creation": False, "evenement": evenement})


@organisateur_required
def supprimer_evenement(request, pk):
    """Suppression d'un événement — réservé à son organisateur propriétaire."""
    evenement = get_object_or_404(Evenement, pk=pk, organisateur=request.user)

    if request.method == "POST":
        evenement.delete()
        messages.success(request, "Événement supprimé.")
        return redirect("dashboard_organisateur")

    return render(request, "events/evenement_confirm_delete.html", {"evenement": evenement})


@organisateur_required
def liste_inscrits(request, pk):
    """Liste des inscrits (confirmés et en attente) à un événement —
    réservé à son organisateur propriétaire."""
    evenement = get_object_or_404(Evenement, pk=pk, organisateur=request.user)
    inscrits_confirmes = evenement.inscriptions.filter(statut=Inscription.Statut.CONFIRMEE)
    inscrits_en_attente = evenement.inscriptions.filter(statut=Inscription.Statut.EN_ATTENTE)
    return render(request, "events/liste_inscrits.html", {
        "evenement": evenement,
        "inscrits_confirmes": inscrits_confirmes,
        "inscrits_en_attente": inscrits_en_attente,
    })


@organisateur_required
def telecharger_excel_inscrits(request, pk):
    """Téléchargement du fichier Excel des inscrits confirmés —
    réservé à l'organisateur propriétaire de l'événement."""
    evenement = get_object_or_404(Evenement, pk=pk, organisateur=request.user)

    chemin = chemin_fichier_excel(evenement)
    if not chemin.exists():
        # Cas rare : aucune confirmation n'a encore eu lieu, donc le fichier
        # n'a jamais été généré. On le crée à la volée (sera vide ou à jour).
        regenerer_excel_evenement(evenement)

    if not chemin.exists():
        raise Http404("Aucun fichier disponible pour cet événement.")

    return FileResponse(
        open(chemin, "rb"),
        as_attachment=True,
        filename=chemin.name,
    )


# ---------------------------------------------------------------------------
# Espace organisateur — moyens de paiement (mobile money direct + CinetPay)
#
# Chaque organisateur active/désactive librement, selon ce qu'il possède
# réellement, les moyens de paiement qu'il propose aux participants de ses
# événements payants. Un moyen désactivé par l'administrateur (voir /admin/
# > Moyens de paiement) reste invisible même si l'organisateur l'a activé
# de son côté (voir CompteReception.objects.disponibles()).
# ---------------------------------------------------------------------------

CompteReceptionFormSet = modelformset_factory(CompteReception, form=CompteReceptionForm, extra=0)


@organisateur_required
def organisateur_moyens_paiement(request):
    """Permet à l'organisateur connecté de configurer ses propres numéros
    mobile money (et d'activer/désactiver CinetPay) pour encaisser
    directement les paiements de SES événements payants."""
    # On s'assure qu'un CompteReception existe pour chaque moyen de paiement
    # actif sur la plateforme, avant d'afficher le formulaire.
    for moyen in MoyenPaiement.objects.filter(actif=True):
        CompteReception.objects.get_or_create(proprietaire=request.user, moyen_paiement=moyen)

    queryset = CompteReception.objects.filter(proprietaire=request.user).select_related("moyen_paiement")

    if request.method == "POST":
        formset = CompteReceptionFormSet(request.POST, queryset=queryset)
        if formset.is_valid():
            formset.save()
            messages.success(request, "Vos moyens de paiement ont été mis à jour.")
            return redirect("organisateur_moyens_paiement")
    else:
        formset = CompteReceptionFormSet(queryset=queryset)

    # On associe chaque formulaire à son moyen de paiement pour l'affichage.
    lignes = list(zip(queryset, formset.forms))

    return render(request, "events/moyens_paiement.html", {"formset": formset, "lignes": lignes})


@organisateur_required
def organisateur_paiements_recus(request):
    """Liste des paiements d'inscriptions (mobile money direct) en attente
    de validation manuelle pour les événements de l'organisateur connecté."""
    paiements_en_attente = Paiement.objects.filter(
        type_paiement=Paiement.Type.INSCRIPTION,
        beneficiaire=request.user,
        statut=Paiement.Statut.EN_ATTENTE_VALIDATION,
    ).select_related("inscription", "inscription__evenement", "moyen_paiement")

    historique = Paiement.objects.filter(
        type_paiement=Paiement.Type.INSCRIPTION,
        beneficiaire=request.user,
    ).exclude(statut=Paiement.Statut.EN_ATTENTE_VALIDATION).select_related(
        "inscription", "inscription__evenement", "moyen_paiement",
    )[:50]

    return render(request, "events/paiements_recus.html", {
        "paiements_en_attente": paiements_en_attente, "historique": historique,
    })


@organisateur_required
@require_POST
def valider_paiement_recu(request, pk):
    """Valide une preuve de paiement d'inscription — réservé au bénéficiaire
    (l'organisateur de l'événement concerné)."""
    paiement = get_object_or_404(
        Paiement, pk=pk, beneficiaire=request.user,
        type_paiement=Paiement.Type.INSCRIPTION, statut=Paiement.Statut.EN_ATTENTE_VALIDATION,
    )
    paiement.valider(valide_par=request.user)
    regenerer_excel_evenement(paiement.inscription.evenement)
    try:
        _envoyer_email_paiement_confirme(request, paiement.inscription)
    except Exception:
        import traceback
        traceback.print_exc()
    messages.success(request, "Paiement validé, l'inscription est confirmée et le participant a été notifié par email.")
    return redirect("organisateur_paiements_recus")


@organisateur_required
@require_POST
def refuser_paiement_recu(request, pk):
    """Refuse une preuve de paiement d'inscription (preuve illisible, montant
    incorrect, numéro erroné...) — réservé au bénéficiaire."""
    paiement = get_object_or_404(
        Paiement, pk=pk, beneficiaire=request.user,
        type_paiement=Paiement.Type.INSCRIPTION, statut=Paiement.Statut.EN_ATTENTE_VALIDATION,
    )
    motif = request.POST.get("motif", "").strip()
    paiement.refuser(motif=motif, valide_par=request.user)
    try:
        _envoyer_email_paiement_refuse(paiement.inscription, motif)
    except Exception:
        import traceback
        traceback.print_exc()
    messages.info(request, "Paiement refusé, le participant a été notifié par email.")
    return redirect("organisateur_paiements_recus")


# ---------------------------------------------------------------------------
# Espace organisateur — abonnement (= le "commerçant" paie pour utiliser
# l'application). Le compte reste inactif tant que l'abonnement n'est pas
# validé (voir Abonnement.activer(), appelé par Paiement.valider()).
# ---------------------------------------------------------------------------

def _organisateur_pour_abonnement(request):
    """Résout l'organisateur concerné par les vues d'abonnement :
    - s'il est connecté (renouvellement d'un compte déjà actif), on utilise
      request.user ;
    - sinon (compte encore inactif : Django ne permet PAS à un utilisateur
      is_active=False de s'authentifier), on utilise l'identifiant mémorisé
      en session lors de l'inscription ou via `retrouver_compte_abonnement`.
    Renvoie None si personne n'a pu être identifié."""
    if request.user.is_authenticated:
        return request.user
    organisateur_id = request.session.get("organisateur_abonnement_id")
    if not organisateur_id:
        return None
    return User.objects.filter(pk=organisateur_id).first()


def organisateur_abonnement(request):
    """Tableau de bord d'abonnement : statut actuel + moyens de paiement
    disponibles pour souscrire/renouveler. Accessible à un compte encore
    inactif (identifié via la session), puisque c'est justement le
    paiement qui débloque le compte."""
    organisateur = _organisateur_pour_abonnement(request)
    if organisateur is None:
        return redirect("retrouver_compte_abonnement")

    config = ConfigurationPlateforme.charger()
    abonnement_actif = Abonnement.objects.filter(organisateur=organisateur).actifs().order_by("-date_fin").first()
    comptes = moyens_disponibles_pour(None)  # comptes de la plateforme
    paiement_en_cours = Paiement.objects.filter(
        type_paiement=Paiement.Type.ABONNEMENT, payeur=organisateur,
        statut=Paiement.Statut.EN_ATTENTE_VALIDATION,
    ).first()

    return render(request, "events/abonnement.html", {
        "organisateur": organisateur, "config": config, "abonnement_actif": abonnement_actif,
        "comptes": comptes, "paiement_en_cours": paiement_en_cours,
    })


def soumettre_preuve_abonnement(request, compte_id):
    """Dépôt de la preuve de paiement Mobile Money direct pour l'abonnement."""
    organisateur = _organisateur_pour_abonnement(request)
    if organisateur is None:
        return redirect("retrouver_compte_abonnement")

    config = ConfigurationPlateforme.charger()
    compte = get_object_or_404(
        CompteReception.objects.disponibles(), pk=compte_id, proprietaire=None,
    )
    if compte.moyen_paiement.est_cinetpay:
        raise Http404("Ce moyen de paiement ne prend pas de preuve manuelle.")

    abonnement, _ = Abonnement.objects.get_or_create(
        organisateur=organisateur, date_debut=None, defaults={"montant": config.montant_abonnement},
    )
    paiement, _ = Paiement.objects.get_or_create(
        abonnement=abonnement,
        defaults={
            "type_paiement": Paiement.Type.ABONNEMENT, "payeur": organisateur,
            "montant": config.montant_abonnement, "moyen_paiement": compte.moyen_paiement,
        },
    )

    if request.method == "POST":
        form = PreuvePaiementForm(request.POST, request.FILES, instance=paiement)
        if form.is_valid():
            paiement = form.save(commit=False)
            paiement.moyen_paiement = compte.moyen_paiement
            paiement.montant = config.montant_abonnement
            paiement.statut = Paiement.Statut.EN_ATTENTE_VALIDATION
            paiement.save()
            messages.success(request, "Votre preuve de paiement a bien été envoyée. Votre compte sera activé après vérification par l'administrateur.")
            return redirect("organisateur_abonnement")
    else:
        form = PreuvePaiementForm(instance=paiement)

    return render(request, "events/paiement_preuve_form.html", {
        "compte": compte, "form": form, "abonnement": True,
    })


def payer_cinetpay_abonnement(request, compte_id):
    """Initialise un paiement CinetPay pour l'abonnement organisateur."""
    organisateur = _organisateur_pour_abonnement(request)
    if organisateur is None:
        return redirect("retrouver_compte_abonnement")

    config = ConfigurationPlateforme.charger()
    compte = get_object_or_404(
        CompteReception.objects.disponibles(), pk=compte_id, proprietaire=None,
        moyen_paiement__code=MoyenPaiement.Code.CINETPAY,
    )

    abonnement, _ = Abonnement.objects.get_or_create(
        organisateur=organisateur, date_debut=None, defaults={"montant": config.montant_abonnement},
    )
    paiement, _ = Paiement.objects.get_or_create(
        abonnement=abonnement,
        defaults={
            "type_paiement": Paiement.Type.ABONNEMENT, "payeur": organisateur,
            "montant": config.montant_abonnement, "moyen_paiement": compte.moyen_paiement,
        },
    )
    if not paiement.cinetpay_transaction_id:
        paiement.cinetpay_transaction_id = f"ABONNEMENT-{organisateur.pk}-{secrets.token_hex(4)}"
    paiement.moyen_paiement = compte.moyen_paiement
    paiement.montant = config.montant_abonnement
    paiement.statut = Paiement.Statut.EN_ATTENTE_CINETPAY
    paiement.save()

    url_retour = request.build_absolute_uri(reverse("cinetpay_retour_abonnement"))
    try:
        payment_url = cinetpay.initier_paiement(
            transaction_id=paiement.cinetpay_transaction_id,
            montant=config.montant_abonnement,
            description="Abonnement organisateur",
            url_retour=url_retour,
            client_nom=organisateur.get_username(),
            client_email=organisateur.email,
        )
    except cinetpay.CinetPayError as exc:
        messages.error(request, f"Paiement CinetPay indisponible pour le moment : {exc}")
        return redirect("organisateur_abonnement")

    return redirect(payment_url)


def cinetpay_retour_abonnement(request):
    """Retour CinetPay pour l'abonnement — même principe de vérification
    systématique côté serveur que pour les inscriptions."""
    organisateur = _organisateur_pour_abonnement(request)
    if organisateur is None:
        return redirect("retrouver_compte_abonnement")

    paiement = Paiement.objects.filter(
        type_paiement=Paiement.Type.ABONNEMENT, payeur=organisateur,
    ).exclude(cinetpay_transaction_id="").order_by("-date_creation").first()

    if not paiement:
        raise Http404("Aucun paiement CinetPay en cours pour cet abonnement.")

    try:
        resultat = cinetpay.verifier_transaction(paiement.cinetpay_transaction_id)
    except cinetpay.CinetPayError as exc:
        messages.error(request, f"Impossible de vérifier votre paiement : {exc}")
        return redirect("organisateur_abonnement")

    if resultat["payee"] and paiement.statut != Paiement.Statut.VALIDE:
        paiement.valider()  # -> déclenche abonnement.activer() (is_active=True)
        messages.success(request, "Paiement reçu, votre compte est activé. Vous pouvez maintenant vous connecter.")
    elif paiement.statut != Paiement.Statut.VALIDE:
        paiement.statut = Paiement.Statut.ECHEC
        paiement.save(update_fields=["statut"])
        messages.error(request, "Le paiement n'a pas abouti. Vous pouvez réessayer.")

    return redirect("organisateur_abonnement")


# ---------------------------------------------------------------------------
# Publications (texte + photos + vidéos) — espace organisateur + public
# ---------------------------------------------------------------------------

@organisateur_required
def organisateur_publications(request):
    publications = Publication.objects.filter(organisateur=request.user).prefetch_related("medias")
    return render(request, "events/publications_dashboard.html", {"publications": publications})


@organisateur_required
def creer_publication(request):
    if request.method == "POST":
        form = PublicationForm(request.POST, request.FILES, organisateur=request.user)
        if form.is_valid():
            publication = Publication.objects.create(
                organisateur=request.user,
                evenement=form.cleaned_data["evenement"],
                texte=form.cleaned_data["texte"].strip(),
            )
            for ordre, fichier in enumerate(form.cleaned_data["medias"]):
                extension = fichier.name.rsplit(".", 1)[-1].lower()
                type_media = PublicationMedia.TypeMedia.VIDEO if extension in EXTENSIONS_VIDEO else PublicationMedia.TypeMedia.PHOTO
                PublicationMedia.objects.create(
                    publication=publication, fichier=fichier, type_media=type_media, ordre=ordre,
                )
            messages.success(request, "Publication créée.")
            return redirect("organisateur_publications")
    else:
        form = PublicationForm(organisateur=request.user)

    return render(request, "events/publication_form.html", {"form": form})


@organisateur_required
@require_POST
def supprimer_publication(request, pk):
    publication = get_object_or_404(Publication, pk=pk, organisateur=request.user)
    publication.delete()
    messages.success(request, "Publication supprimée.")
    return redirect("organisateur_publications")


def liste_publications(request):
    """Fil des publications.

    - Organisateur connecté : uniquement SES propres publications (comme
      dans son espace privé), pour éviter qu'il voie/confonde celles des
      autres organisateurs sur la page "Actualités".
    - Visiteur non connecté (ou compte non-organisateur) : fil public,
      tous organisateurs actifs confondus.
    """
    if request.user.is_authenticated and not request.user.is_staff:
        publications = Publication.objects.filter(organisateur=request.user)
    else:
        publications = Publication.objects.filter(organisateur__is_active=True)

    publications = publications.select_related("organisateur", "evenement").prefetch_related("medias")
    return render(request, "events/publications_liste.html", {"publications": publications})