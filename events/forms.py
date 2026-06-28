from django import forms
from django.contrib.auth.forms import UserCreationForm, AuthenticationForm
from django.contrib.auth import get_user_model
from .models import Inscription, Evenement

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
        fields = ["titre", "description", "date_debut", "date_fin", "lieu", "places_totales"]
        widgets = {
            "titre": forms.TextInput(attrs={"class": "form-control"}),
            "description": forms.Textarea(attrs={"class": "form-control", "rows": 4}),
            "date_debut": forms.DateTimeInput(attrs={"class": "form-control", "type": "datetime-local"}),
            "date_fin": forms.DateTimeInput(attrs={"class": "form-control", "type": "datetime-local"}),
            "lieu": forms.TextInput(attrs={"class": "form-control"}),
            "places_totales": forms.NumberInput(attrs={"class": "form-control", "min": 1}),
        }

    def clean(self):
        cleaned_data = super().clean()
        date_debut = cleaned_data.get("date_debut")
        date_fin = cleaned_data.get("date_fin")
        if date_debut and date_fin and date_fin < date_debut:
            raise forms.ValidationError("La date de fin ne peut pas être avant la date de début.")
        return cleaned_data
