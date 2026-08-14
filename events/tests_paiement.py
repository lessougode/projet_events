from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from django.core import mail

from .models import (
    Evenement, Inscription, MoyenPaiement, CompteReception, Paiement,
    ConfigurationPlateforme, Abonnement, Publication,
)

User = get_user_model()


def creer_organisateur(username="organisateur_paiement"):
    return User.objects.create_user(username=username, password="motdepasse123", email=f"{username}@test.com")


def creer_evenement_payant(organisateur=None, prix=5000, places_totales=5):
    if organisateur is None:
        organisateur = creer_organisateur()
    debut = timezone.now() + timedelta(days=7)
    return Evenement.objects.create(
        organisateur=organisateur, titre="Formation Django payante",
        date_debut=debut, date_fin=debut, lieu="Abidjan",
        places_totales=places_totales, est_payant=True, prix=prix,
    )


def petite_image():
    contenu = (
        b"GIF87a\x01\x00\x01\x00\x80\x00\x00\x00\x00\x00\xff\xff\xff!\xf9"
        b"\x04\x01\x00\x00\x00\x00,\x00\x00\x00\x00\x01\x00\x01\x00\x00\x02\x02D\x01\x00;"
    )
    return SimpleUploadedFile("preuve.gif", contenu, content_type="image/gif")


class PaiementInscriptionTests(TestCase):
    def setUp(self):
        # Un moyen mobile money + un compte de réception actif chez l'organisateur.
        self.moyen, _ = MoyenPaiement.objects.get_or_create(code=MoyenPaiement.Code.ORANGE_MONEY, defaults={"actif": True})
        self.moyen.actif = True
        self.moyen.save()
        self.organisateur = creer_organisateur()
        self.evenement = creer_evenement_payant(organisateur=self.organisateur)
        self.compte = CompteReception.objects.create(
            proprietaire=self.organisateur, moyen_paiement=self.moyen,
            numero_reception="0700000000", nom_beneficiaire="Test Orga", actif=True,
        )

    def _inscrire_et_confirmer_email(self):
        url = reverse("inscription_evenement", args=[self.evenement.pk])
        self.client.post(url, {
            "nom": "Kouassi", "prenoms": "Awa", "telephone1": "0102030405",
            "ville": "Abidjan", "email": "awa@test.com",
        })
        inscription = Inscription.objects.get(email="awa@test.com")
        inscription.confirmer()
        inscription.refresh_from_db()
        return inscription

    def test_evenement_payant_passe_en_attente_paiement_apres_email_confirme(self):
        inscription = self._inscrire_et_confirmer_email()
        self.assertEqual(inscription.statut, Inscription.Statut.EMAIL_CONFIRME)
        self.assertEqual(self.evenement.places_restantes, 5)  # pas encore décomptée

    def test_page_choix_paiement_liste_les_comptes_actifs(self):
        inscription = self._inscrire_et_confirmer_email()
        url = reverse("choisir_paiement_inscription", args=[inscription.token_confirmation])
        response = self.client.get(url)
        self.assertContains(response, "Orange Money")
        self.assertContains(response, "0700000000")

    def test_depot_preuve_cree_paiement_en_attente_de_validation(self):
        inscription = self._inscrire_et_confirmer_email()
        url = reverse("soumettre_preuve_inscription", args=[inscription.token_confirmation, self.compte.pk])
        response = self.client.post(url, {
            "numero_expediteur": "0708091011",
            "preuve_paiement": petite_image(),
            "reference_saisie": "REF123",
        })
        self.assertRedirects(response, reverse("paiement_soumis", args=[inscription.token_confirmation]))

        paiement = Paiement.objects.get(inscription=inscription)
        self.assertEqual(paiement.statut, Paiement.Statut.EN_ATTENTE_VALIDATION)
        self.assertEqual(paiement.montant, self.evenement.prix)
        # L'inscription n'est toujours PAS confirmée tant que l'organisateur n'a pas validé.
        inscription.refresh_from_db()
        self.assertEqual(inscription.statut, Inscription.Statut.EMAIL_CONFIRME)

    def test_organisateur_valide_paiement_confirme_inscription_et_envoie_email(self):
        inscription = self._inscrire_et_confirmer_email()
        paiement = Paiement.objects.create(
            type_paiement=Paiement.Type.INSCRIPTION, inscription=inscription,
            beneficiaire=self.organisateur, moyen_paiement=self.moyen,
            montant=self.evenement.prix, statut=Paiement.Statut.EN_ATTENTE_VALIDATION,
            numero_expediteur="0708091011",
        )
        self.client.login(username=self.organisateur.username, password="motdepasse123")
        mail.outbox = []
        url = reverse("valider_paiement_recu", args=[paiement.pk])
        response = self.client.post(url)
        self.assertRedirects(response, reverse("organisateur_paiements_recus"))

        inscription.refresh_from_db()
        paiement.refresh_from_db()
        self.assertEqual(inscription.statut, Inscription.Statut.CONFIRMEE)
        self.assertEqual(paiement.statut, Paiement.Statut.VALIDE)
        self.assertEqual(self.evenement.places_restantes, 4)
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("awa@test.com", mail.outbox[0].to)

    def test_autre_organisateur_ne_peut_pas_valider_paiement_dautrui(self):
        inscription = self._inscrire_et_confirmer_email()
        paiement = Paiement.objects.create(
            type_paiement=Paiement.Type.INSCRIPTION, inscription=inscription,
            beneficiaire=self.organisateur, moyen_paiement=self.moyen,
            montant=self.evenement.prix, statut=Paiement.Statut.EN_ATTENTE_VALIDATION,
        )
        intrus = creer_organisateur("intrus")
        self.client.login(username="intrus", password="motdepasse123")
        response = self.client.post(reverse("valider_paiement_recu", args=[paiement.pk]))
        self.assertEqual(response.status_code, 404)
        paiement.refresh_from_db()
        self.assertEqual(paiement.statut, Paiement.Statut.EN_ATTENTE_VALIDATION)

    def test_moyen_paiement_desactive_par_admin_disparait_meme_si_organisateur_actif(self):
        self.moyen.actif = False
        self.moyen.save()
        inscription = self._inscrire_et_confirmer_email()
        url = reverse("choisir_paiement_inscription", args=[inscription.token_confirmation])
        response = self.client.get(url)
        self.assertNotContains(response, "Orange Money")


class AbonnementTests(TestCase):
    def setUp(self):
        self.moyen, _ = MoyenPaiement.objects.get_or_create(code=MoyenPaiement.Code.MTN_MOMO, defaults={"actif": True})
        self.moyen.actif = True
        self.moyen.save()
        self.compte_plateforme = CompteReception.objects.create(
            proprietaire=None, moyen_paiement=self.moyen, numero_reception="0500000000", actif=True,
        )
        ConfigurationPlateforme.objects.get_or_create(pk=1, defaults={"montant_abonnement": 5000, "duree_abonnement_jours": 30})
        self.organisateur = creer_organisateur("commercant")
        self.organisateur.is_active = False
        self.organisateur.save(update_fields=["is_active"])

    def test_soumission_preuve_abonnement_cree_paiement_en_attente(self):
        # Un compte inactif ne peut pas se connecter : on simule le
        # mécanisme de session mis en place à l'inscription.
        session = self.client.session
        session["organisateur_abonnement_id"] = self.organisateur.pk
        session.save()
        url = reverse("soumettre_preuve_abonnement", args=[self.compte_plateforme.pk])
        response = self.client.post(url, {
            "numero_expediteur": "0708091011", "preuve_paiement": petite_image(), "reference_saisie": "",
        })
        self.assertRedirects(response, reverse("organisateur_abonnement"))
        paiement = Paiement.objects.get(type_paiement=Paiement.Type.ABONNEMENT, payeur=self.organisateur)
        self.assertEqual(paiement.statut, Paiement.Statut.EN_ATTENTE_VALIDATION)
        self.organisateur.refresh_from_db()
        self.assertFalse(self.organisateur.is_active)  # pas encore activé

    def test_sans_identification_redirige_vers_retrouver_compte(self):
        response = self.client.get(reverse("organisateur_abonnement"))
        self.assertRedirects(response, reverse("retrouver_compte_abonnement"))

    def test_validation_paiement_abonnement_active_le_compte(self):
        abonnement = Abonnement.objects.create(organisateur=self.organisateur, montant=5000)
        paiement = Paiement.objects.create(
            type_paiement=Paiement.Type.ABONNEMENT, payeur=self.organisateur, abonnement=abonnement,
            moyen_paiement=self.moyen, montant=5000, statut=Paiement.Statut.EN_ATTENTE_VALIDATION,
        )
        paiement.valider()
        self.organisateur.refresh_from_db()
        abonnement.refresh_from_db()
        self.assertTrue(self.organisateur.is_active)
        self.assertTrue(abonnement.est_actif)


class PublicationTests(TestCase):
    def setUp(self):
        self.organisateur = creer_organisateur("publieur")

    def test_creation_publication_avec_photo(self):
        self.client.force_login(self.organisateur)
        url = reverse("creer_publication")
        response = self.client.post(url, {
            "texte": "Une belle photo de notre événement !",
            "evenement": "",
            "medias": [petite_image()],
        })
        self.assertRedirects(response, reverse("organisateur_publications"))
        publication = Publication.objects.get(organisateur=self.organisateur)
        self.assertEqual(publication.medias.count(), 1)
        self.assertEqual(publication.medias.first().type_media, "PHOTO")

    def test_publication_vide_refusee(self):
        self.client.force_login(self.organisateur)
        response = self.client.post(reverse("creer_publication"), {"texte": "", "evenement": ""})
        self.assertEqual(response.status_code, 200)  # reste sur le formulaire
        self.assertEqual(Publication.objects.count(), 0)

    def test_liste_publique_visible_sans_connexion(self):
        publication = Publication.objects.create(organisateur=self.organisateur, texte="Coucou tout le monde")
        response = self.client.get(reverse("liste_publications"))
        self.assertContains(response, "Coucou tout le monde")

    def test_organisateur_desactive_masque_de_la_liste_publique(self):
        Publication.objects.create(organisateur=self.organisateur, texte="Texte masqué")
        self.organisateur.is_active = False
        self.organisateur.save(update_fields=["is_active"])
        response = self.client.get(reverse("liste_publications"))
        self.assertNotContains(response, "Texte masqué")
