



from asyncio.log import logger
from functools import wraps

from django.shortcuts import render, redirect, get_object_or_404
from django.utils import timezone
from utils import send_email_with_template

from django.core.mail import send_mail

from django.conf import settings
from django.db import IntegrityError
from django.contrib import messages
from django.contrib.auth import logout
from django.contrib.auth.decorators import login_required
from django.http import FileResponse, Http404
from django.urls import reverse

from .models import Evenement, Inscription
from .forms import InscriptionForm, OrganisateurCreationForm, EvenementForm
from .excel_export import regenerer_excel_evenement, chemin_fichier_excel


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
# Paiement visiteur (PayPal / CinetPay)
#
# Flux : email confirmé (EMAIL_CONFIRME) -> choix du moyen de paiement
# -> redirection vers le prestataire -> retour sur le site -> vérification
# réelle du statut auprès du prestataire -> confirmer_paiement() si réussi.
#
# IMPORTANT : on ne fait jamais confiance aux seuls paramètres de l'URL de
# retour pour valider un paiement (un visiteur malveillant pourrait
# fabriquer une URL de succès sans avoir payé). On revérifie toujours le
# statut réel auprès du prestataire avant de confirmer quoi que ce soit.
# ---------------------------------------------------------------------------


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
            form.save()
            return redirect("compte_en_attente")
    else:
        form = OrganisateurCreationForm()

    return render(request, "events/inscription_organisateur.html", {"form": form})


def compte_en_attente(request):
    """Page affichée après inscription, tant que le compte n'est pas encore activé."""
    return render(request, "events/compte_en_attente.html")


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
