from django import forms
from django.contrib.auth.forms import UserCreationForm, AuthenticationForm
from django.contrib.auth import get_user_model
from .models import (
    Inscription, Evenement, CompteReception, Paiement,
    Publication, PublicationMedia, EXTENSIONS_PHOTO, EXTENSIONS_VIDEO,
)

User = get_user_model()


class InscriptionForm(forms.ModelForm):
    """Formulaire d'inscription visiteur, sans création de compte.
    L'inscription est créée en statut EN_ATTENTE et devra être confirmée
    par email (double opt-in) avant d'être définitivement validée."""

    class Meta:
        model = Inscription
        fields = ["nom", "prenoms", "telephone1", "ville", "email"]
        widgets = {
            "nom": forms.TextInput(attrs={
                "class": "form-control",
                "placeholder": "Votre nom",
                "autofocus": True,
            }),
            "prenoms": forms.TextInput(attrs={
                "class": "form-control",
                "placeholder": "Vos prénoms",
            }),
            "telephone1": forms.TextInput(attrs={
                "class": "form-control",
                "placeholder": "Ex : 07 00 00 00 00",
            }),
            "ville": forms.TextInput(attrs={
                "class": "form-control",
                "placeholder": "Votre ville",
            }),
            "email": forms.EmailInput(attrs={
                "class": "form-control",
                "placeholder": "votre.email@exemple.com",
            }),
        }
        labels = {
            "nom": "Nom",
            "prenoms": "Prénoms",
            "telephone1": "Téléphone",
            "ville": "Ville",
            "email": "Adresse email",
        }

    def clean_nom(self):
        nom = self.cleaned_data["nom"].strip()
        if len(nom) < 2:
            raise forms.ValidationError("Veuillez indiquer un nom valide.")
        return nom

    def clean_prenoms(self):
        prenoms = self.cleaned_data["prenoms"].strip()
        if len(prenoms) < 2:
            raise forms.ValidationError("Veuillez indiquer des prénoms valides.")
        return prenoms

    def clean_telephone1(self):
        telephone = self.cleaned_data["telephone1"].strip()
        chiffres = "".join(c for c in telephone if c.isdigit())
        if len(chiffres) < 8:
            raise forms.ValidationError("Veuillez indiquer un numéro de téléphone valide.")
        return telephone

    def clean_ville(self):
        ville = self.cleaned_data["ville"].strip()
        if len(ville) < 2:
            raise forms.ValidationError("Veuillez indiquer une ville valide.")
        return ville

    def clean_email(self):
        # Normalisation : évite que "Test@Mail.com" et "test@mail.com"
        # soient considérés comme deux emails différents.
        return self.cleaned_data["email"].strip().lower()


class OrganisateurCreationForm(UserCreationForm):
    """Formulaire d'inscription libre pour un organisateur (compte avec mot de passe)."""

    email = forms.EmailField(
        required=True,
        widget=forms.EmailInput(attrs={"class": "form-control", "placeholder": "votre.email@exemple.com"}),
    )

    class Meta:
        model = User
        fields = ["username", "email", "password1", "password2"]
        widgets = {
            "username": forms.TextInput(attrs={"class": "form-control", "placeholder": "Nom d'utilisateur"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["password1"].widget.attrs.update({"class": "form-control"})
        self.fields["password2"].widget.attrs.update({"class": "form-control"})

    def clean_email(self):
        email = self.cleaned_data["email"].strip().lower()
        if User.objects.filter(email=email).exists():
            raise forms.ValidationError("Un compte existe déjà avec cet email.")
        return email

    def save(self, commit=True):
        user = super().save(commit=False)
        user.email = self.cleaned_data["email"]
        # Compte créé inactif : l'accès à l'espace organisateur n'est débloqué
        # qu'après activation manuelle par l'administrateur (paiement reçu
        # en direct, hors application). Voir /admin/ > Utilisateurs.
        user.is_active = False
        if commit:
            user.save()
        return user


class OrganisateurAuthenticationForm(AuthenticationForm):
    """Formulaire de connexion organisateur, avec un message explicite
    quand le compte existe mais n'a pas encore été activé (paiement non
    encore reçu/traité) plutôt que le message Django générique."""

    error_messages = {
        **AuthenticationForm.error_messages,
        "inactive": (
            "Votre compte n'est pas encore activé. Il sera débloqué dès "
            "réception de votre paiement. Contactez l'administrateur si "
            "vous avez déjà réglé."
        ),
    }


class EvenementForm(forms.ModelForm):
    """Formulaire de création/édition d'un événement par son organisateur."""

    class Meta:
        model = Evenement
        fields = ["titre", "description", "date_debut", "date_fin", "lieu", "places_totales", "est_payant", "prix"]
        widgets = {
            "titre": forms.TextInput(attrs={"class": "form-control"}),
            "description": forms.Textarea(attrs={"class": "form-control", "rows": 4}),
            "date_debut": forms.DateTimeInput(attrs={"class": "form-control", "type": "datetime-local"}),
            "date_fin": forms.DateTimeInput(attrs={"class": "form-control", "type": "datetime-local"}),
            "lieu": forms.TextInput(attrs={"class": "form-control"}),
            "places_totales": forms.NumberInput(attrs={"class": "form-control", "min": 1}),
            "est_payant": forms.CheckboxInput(attrs={"class": "form-check-input"}),
            "prix": forms.NumberInput(attrs={"class": "form-control", "min": 0, "placeholder": "Ex : 5000"}),
        }
        labels = {
            "est_payant": "Cet événement/formation est payant",
            "prix": "Prix par participant (FCFA)",
        }

    def clean(self):
        cleaned_data = super().clean()
        date_debut = cleaned_data.get("date_debut")
        date_fin = cleaned_data.get("date_fin")
        if date_debut and date_fin and date_fin < date_debut:
            raise forms.ValidationError("La date de fin ne peut pas être avant la date de début.")

        # RG : un événement payant doit avoir un prix > 0 ; on nettoie aussi
        # le prix d'un événement gratuit pour éviter toute confusion en base.
        if cleaned_data.get("est_payant"):
            if not cleaned_data.get("prix"):
                self.add_error("prix", "Indiquez un prix : l'événement est marqué comme payant.")
        else:
            cleaned_data["prix"] = None
        return cleaned_data


# ---------------------------------------------------------------------------
# Paiements
# ---------------------------------------------------------------------------

class CompteReceptionForm(forms.ModelForm):
    """Un organisateur (ou l'admin pour le compte plateforme) active/désactive
    un moyen de paiement et renseigne son numéro de réception."""

    class Meta:
        model = CompteReception
        fields = ["numero_reception", "nom_beneficiaire", "actif"]
        widgets = {
            "numero_reception": forms.TextInput(attrs={"class": "form-control", "placeholder": "Ex : 07 00 00 00 00"}),
            "nom_beneficiaire": forms.TextInput(attrs={"class": "form-control", "placeholder": "Nom affiché au payeur"}),
            "actif": forms.CheckboxInput(attrs={"class": "form-check-input"}),
        }


class PreuvePaiementForm(forms.ModelForm):
    """Formulaire de dépôt de preuve pour un paiement Mobile Money direct
    (capture d'écran + numéro émetteur), utilisé aussi bien pour un
    abonnement organisateur que pour une inscription payante."""

    class Meta:
        model = Paiement
        fields = ["numero_expediteur", "preuve_paiement", "reference_saisie"]
        widgets = {
            "numero_expediteur": forms.TextInput(attrs={
                "class": "form-control", "placeholder": "Le numéro depuis lequel vous avez envoyé l'argent",
            }),
            "preuve_paiement": forms.ClearableFileInput(attrs={"class": "form-control", "accept": "image/*"}),
            "reference_saisie": forms.TextInput(attrs={
                "class": "form-control", "placeholder": "Référence de la transaction (facultatif)",
            }),
        }
        labels = {
            "numero_expediteur": "Votre numéro (émetteur)",
            "preuve_paiement": "Capture d'écran du paiement",
            "reference_saisie": "Référence / ID de la transaction",
        }

    def clean_preuve_paiement(self):
        fichier = self.cleaned_data.get("preuve_paiement")
        if not fichier:
            raise forms.ValidationError("La capture d'écran du paiement est obligatoire.")
        if fichier.size > 5 * 1024 * 1024:
            raise forms.ValidationError("Le fichier est trop volumineux (5 Mo maximum).")
        return fichier

    def clean_numero_expediteur(self):
        numero = self.cleaned_data["numero_expediteur"].strip()
        chiffres = "".join(c for c in numero if c.isdigit())
        if len(chiffres) < 8:
            raise forms.ValidationError("Veuillez indiquer un numéro de téléphone valide.")
        return numero


# ---------------------------------------------------------------------------
# Publications (texte + photos + vidéos)
# ---------------------------------------------------------------------------

class MultipleFileInput(forms.ClearableFileInput):
    allow_multiple_selected = True


class MultipleFileField(forms.FileField):
    """Champ permettant de sélectionner plusieurs fichiers d'un coup dans
    le même <input>, tout en validant chacun individuellement."""

    def __init__(self, *args, **kwargs):
        kwargs.setdefault("widget", MultipleFileInput(attrs={"class": "form-control", "multiple": True}))
        super().__init__(*args, **kwargs)

    def clean(self, data, initial=None):
        single_file_clean = super().clean
        if isinstance(data, (list, tuple)):
            return [single_file_clean(fichier, initial) for fichier in data]
        return [single_file_clean(data, initial)] if data else []


class PublicationForm(forms.Form):
    """Formulaire de création d'une publication : texte libre + plusieurs
    photos/vidéos en une seule fois. Au moins un des deux est requis."""

    texte = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={"class": "form-control", "rows": 4, "placeholder": "Écrivez votre publication…"}),
        label="Texte",
    )
    evenement = forms.ModelChoiceField(
        queryset=Evenement.objects.none(),
        required=False,
        widget=forms.Select(attrs={"class": "form-select"}),
        label="Lier à un événement (facultatif)",
    )
    medias = MultipleFileField(required=False, label="Photos / vidéos")

    def __init__(self, *args, organisateur=None, **kwargs):
        super().__init__(*args, **kwargs)
        if organisateur is not None:
            self.fields["evenement"].queryset = Evenement.objects.filter(organisateur=organisateur)

    def clean(self):
        cleaned_data = super().clean()
        texte = (cleaned_data.get("texte") or "").strip()
        medias = cleaned_data.get("medias") or []
        if not texte and not medias:
            raise forms.ValidationError("Ajoutez au moins du texte, une photo ou une vidéo.")
        return cleaned_data

    def clean_medias(self):
        fichiers = self.cleaned_data.get("medias") or []
        extensions_valides = set(EXTENSIONS_PHOTO) | set(EXTENSIONS_VIDEO)
        for fichier in fichiers:
            extension = fichier.name.rsplit(".", 1)[-1].lower() if "." in fichier.name else ""
            if extension not in extensions_valides:
                raise forms.ValidationError(f"Format non supporté : « {fichier.name} ». Photos : jpg/png/webp/gif. Vidéos : mp4/webm/mov/m4v.")
            if fichier.size > 50 * 1024 * 1024:
                raise forms.ValidationError(f"« {fichier.name} » dépasse la taille maximale autorisée (50 Mo).")
        return fichiers
