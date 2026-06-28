from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from django.core import mail

from .models import Evenement, Inscription

User = get_user_model()


def creer_organisateur(username="organisateur1"):
    return User.objects.create_user(username=username, password="motdepasse123", email=f"{username}@test.com")


def creer_evenement(organisateur=None, places_totales=2, jours_avant=7, duree_jours=1):
    if organisateur is None:
        organisateur = creer_organisateur()
    debut = timezone.now() + timedelta(days=jours_avant)
    return Evenement.objects.create(
        organisateur=organisateur,
        titre="Conférence Django",
        description="Une super conférence.",
        date_debut=debut,
        date_fin=debut + timedelta(days=duree_jours - 1),
        lieu="Paris",
        places_totales=places_totales,
    )


def creer_inscription(evenement, email="alice@test.com", statut=Inscription.Statut.CONFIRMEE):
    inscription = Inscription.objects.create(
        evenement=evenement,
        nom="Dupont",
        prenoms="Alice",
        telephone1="0700000000",
        ville="Abidjan",
        email=email,
        statut=statut,
    )
    if statut == Inscription.Statut.CONFIRMEE:
        inscription.date_confirmation = timezone.now()
        inscription.save(update_fields=["date_confirmation"])
    return inscription


class EvenementModelTests(TestCase):
    def test_places_restantes_ne_compte_que_les_confirmees(self):
        evenement = creer_evenement(places_totales=2)
        self.assertEqual(evenement.places_restantes, 2)

        creer_inscription(evenement, email="alice@test.com", statut=Inscription.Statut.CONFIRMEE)
        self.assertEqual(evenement.places_restantes, 1)

        # Une inscription EN_ATTENTE ne décompte aucune place (RG : place
        # comptée seulement après confirmation par email)
        creer_inscription(evenement, email="bob@test.com", statut=Inscription.Statut.EN_ATTENTE)
        self.assertEqual(evenement.places_restantes, 1)

    def test_evenement_sur_un_seul_jour(self):
        evenement = creer_evenement(duree_jours=1)
        self.assertTrue(evenement.sur_un_seul_jour)
        self.assertEqual(evenement.duree_en_jours, 1)

    def test_formation_sur_plusieurs_jours(self):
        evenement = creer_evenement(duree_jours=3)
        self.assertFalse(evenement.sur_un_seul_jour)
        self.assertEqual(evenement.duree_en_jours, 3)


class InscriptionModelTests(TestCase):
    def test_confirmer_inscription_valide(self):
        evenement = creer_evenement(places_totales=5)
        inscription = creer_inscription(evenement, statut=Inscription.Statut.EN_ATTENTE)

        reussite = inscription.confirmer()

        self.assertTrue(reussite)
        inscription.refresh_from_db()
        self.assertEqual(inscription.statut, Inscription.Statut.CONFIRMEE)
        self.assertIsNotNone(inscription.date_confirmation)

    def test_confirmer_inscription_expiree_echoue(self):
        evenement = creer_evenement(places_totales=5)
        inscription = creer_inscription(evenement, statut=Inscription.Statut.EN_ATTENTE)
        inscription.date_expiration = timezone.now() - timedelta(hours=1)
        inscription.save(update_fields=["date_expiration"])

        reussite = inscription.confirmer()

        self.assertFalse(reussite)
        inscription.refresh_from_db()
        self.assertEqual(inscription.statut, Inscription.Statut.EXPIREE)

    def test_confirmer_inscription_si_evenement_complet_entre_temps(self):
        evenement = creer_evenement(places_totales=1)
        # Une place déjà prise par quelqu'un d'autre, confirmée entre-temps
        creer_inscription(evenement, email="premier@test.com", statut=Inscription.Statut.CONFIRMEE)
        inscription = creer_inscription(evenement, email="second@test.com", statut=Inscription.Statut.EN_ATTENTE)

        reussite = inscription.confirmer()

        self.assertFalse(reussite)
        inscription.refresh_from_db()
        self.assertEqual(inscription.statut, Inscription.Statut.EN_ATTENTE)  # reste en attente, pas expirée


class InscriptionVueTests(TestCase):
    def test_formulaire_cree_inscription_en_attente_et_envoie_email(self):
        evenement = creer_evenement(places_totales=5)
        url = reverse("inscription_evenement", args=[evenement.pk])

        response = self.client.post(url, {
            "nom": "Dupont",
            "prenoms": "Alice",
            "telephone1": "0700000000",
            "ville": "Abidjan",
            "email": "alice@test.com",
        })

        self.assertRedirects(response, reverse("verifier_votre_email", args=[evenement.pk]))
        self.assertEqual(Inscription.objects.count(), 1)

        inscription = Inscription.objects.first()
        self.assertEqual(inscription.statut, Inscription.Statut.EN_ATTENTE)
        self.assertEqual(evenement.places_restantes, 5)  # pas encore décomptée

        self.assertEqual(len(mail.outbox), 1)
        self.assertIn(inscription.token_confirmation, mail.outbox[0].body)

    def test_clic_lien_confirmation_valide_inscription(self):
        evenement = creer_evenement(places_totales=5)
        inscription = creer_inscription(evenement, statut=Inscription.Statut.EN_ATTENTE)
        url = reverse("confirmer_inscription", args=[inscription.token_confirmation])

        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)
        inscription.refresh_from_db()
        self.assertEqual(inscription.statut, Inscription.Statut.CONFIRMEE)
        self.assertEqual(evenement.places_restantes, 4)

    def test_lien_confirmation_invalide_404(self):
        url = reverse("confirmer_inscription", args=["token-inexistant"])
        response = self.client.get(url)
        self.assertEqual(response.status_code, 404)

    def test_double_inscription_active_meme_email_refusee(self):
        evenement = creer_evenement(places_totales=5)
        creer_inscription(evenement, email="alice@test.com", statut=Inscription.Statut.EN_ATTENTE)
        url = reverse("inscription_evenement", args=[evenement.pk])

        response = self.client.post(url, {
            "nom": "Dupont", "prenoms": "Alice Bis", "telephone1": "0700000000",
            "ville": "Abidjan", "email": "alice@test.com",
        })

        self.assertEqual(response.status_code, 200)  # reste sur le formulaire
        self.assertEqual(Inscription.objects.count(), 1)  # pas de doublon créé

    def test_reinscription_possible_apres_expiration(self):
        evenement = creer_evenement(places_totales=5)
        expiree = creer_inscription(evenement, email="alice@test.com", statut=Inscription.Statut.EXPIREE)
        url = reverse("inscription_evenement", args=[evenement.pk])

        response = self.client.post(url, {
            "nom": "Dupont", "prenoms": "Alice", "telephone1": "0700000000",
            "ville": "Abidjan", "email": "alice@test.com",
        })

        self.assertRedirects(response, reverse("verifier_votre_email", args=[evenement.pk]))
        self.assertEqual(Inscription.objects.filter(email="alice@test.com").count(), 2)

    def test_inscription_impossible_si_evenement_complet(self):
        evenement = creer_evenement(places_totales=1)
        creer_inscription(evenement, email="alice@test.com", statut=Inscription.Statut.CONFIRMEE)
        url = reverse("inscription_evenement", args=[evenement.pk])

        response = self.client.get(url)

        self.assertContains(response, "complet")

    def test_liste_evenements_affiche_uniquement_evenements_futurs(self):
        futur = creer_evenement(jours_avant=5)
        passe = Evenement.objects.create(
            organisateur=creer_organisateur("organisateur2"),
            titre="Événement passé",
            date_debut=timezone.now() - timedelta(days=2),
            date_fin=timezone.now() - timedelta(days=1),
            lieu="Lyon",
            places_totales=10,
        )

        response = self.client.get(reverse("liste_evenements"))

        self.assertContains(response, futur.titre)
        self.assertNotContains(response, passe.titre)


class MultiTenantIsolationTests(TestCase):
    """Vérifie qu'un organisateur ne peut jamais accéder aux événements d'un autre."""

    def test_organisateur_ne_voit_que_ses_evenements_dans_dashboard(self):
        org1 = creer_organisateur("org1")
        org2 = creer_organisateur("org2")
        evt_org1 = creer_evenement(organisateur=org1)
        evt_org2 = creer_evenement(organisateur=org2)

        self.client.login(username="org1", password="motdepasse123")
        response = self.client.get(reverse("dashboard_organisateur"))

        self.assertContains(response, evt_org1.titre)
        self.assertNotContains(response, evt_org2.titre)

    def test_organisateur_ne_peut_pas_modifier_evenement_dautrui(self):
        org1 = creer_organisateur("org1")
        org2 = creer_organisateur("org2")
        evt_org2 = creer_evenement(organisateur=org2)

        self.client.login(username="org1", password="motdepasse123")
        response = self.client.get(reverse("modifier_evenement", args=[evt_org2.pk]))

        self.assertEqual(response.status_code, 404)  # pas 403 : ne révèle pas l'existence

    def test_organisateur_ne_peut_pas_voir_inscrits_dautrui(self):
        org1 = creer_organisateur("org1")
        org2 = creer_organisateur("org2")
        evt_org2 = creer_evenement(organisateur=org2)

        self.client.login(username="org1", password="motdepasse123")
        response = self.client.get(reverse("liste_inscrits", args=[evt_org2.pk]))

        self.assertEqual(response.status_code, 404)

    def test_visiteur_non_connecte_ne_peut_pas_acceder_au_dashboard(self):
        response = self.client.get(reverse("dashboard_organisateur"))
        self.assertEqual(response.status_code, 302)  # redirigé vers la connexion


class ExpirationInscriptionsCommandTests(TestCase):
    def test_commande_expire_les_inscriptions_depassees(self):
        from django.core.management import call_command

        evenement = creer_evenement(places_totales=5)
        expiree = creer_inscription(evenement, email="expire@test.com", statut=Inscription.Statut.EN_ATTENTE)
        expiree.date_expiration = timezone.now() - timedelta(hours=1)
        expiree.save(update_fields=["date_expiration"])

        recente = creer_inscription(evenement, email="recente@test.com", statut=Inscription.Statut.EN_ATTENTE)

        call_command("expirer_inscriptions")

        expiree.refresh_from_db()
        recente.refresh_from_db()
        self.assertEqual(expiree.statut, Inscription.Statut.EXPIREE)
        self.assertEqual(recente.statut, Inscription.Statut.EN_ATTENTE)


class OrganisateurDesactiveTests(TestCase):
    """Vérifie qu'un organisateur désactivé (is_active=False) perd tout accès
    public et privé, immédiatement — y compris s'il avait déjà une session
    ouverte au moment de la désactivation."""

    def test_evenements_masques_de_la_liste_publique(self):
        org = creer_organisateur("org_desactive")
        evenement = creer_evenement(organisateur=org)

        org.is_active = False
        org.save(update_fields=["is_active"])

        response = self.client.get(reverse("liste_evenements"))
        self.assertNotContains(response, evenement.titre)

    def test_detail_evenement_renvoie_404_si_organisateur_desactive(self):
        org = creer_organisateur("org_desactive")
        evenement = creer_evenement(organisateur=org)

        org.is_active = False
        org.save(update_fields=["is_active"])

        response = self.client.get(reverse("detail_evenement", args=[evenement.pk]))
        self.assertEqual(response.status_code, 404)

    def test_inscription_impossible_si_organisateur_desactive(self):
        org = creer_organisateur("org_desactive")
        evenement = creer_evenement(organisateur=org)

        org.is_active = False
        org.save(update_fields=["is_active"])

        response = self.client.get(reverse("inscription_evenement", args=[evenement.pk]))
        self.assertEqual(response.status_code, 404)

    def test_confirmation_echoue_si_organisateur_desactive_entre_temps(self):
        org = creer_organisateur("org_desactive")
        evenement = creer_evenement(organisateur=org, places_totales=5)
        inscription = creer_inscription(evenement, statut=Inscription.Statut.EN_ATTENTE)

        # L'organisateur est désactivé après l'envoi de l'email mais avant le clic
        org.is_active = False
        org.save(update_fields=["is_active"])

        reussite = inscription.confirmer()

        self.assertFalse(reussite)
        inscription.refresh_from_db()
        self.assertEqual(inscription.statut, Inscription.Statut.EN_ATTENTE)

    def test_session_existante_coupee_immediatement_apres_desactivation(self):
        org = creer_organisateur("org_desactive")
        creer_evenement(organisateur=org)

        self.client.login(username="org_desactive", password="motdepasse123")
        # Vérifie que la session est valide avant désactivation
        response = self.client.get(reverse("dashboard_organisateur"))
        self.assertEqual(response.status_code, 200)

        # Désactivation pendant que la session est toujours ouverte
        org.is_active = False
        org.save(update_fields=["is_active"])

        # La même session (même client) doit maintenant être rejetée
        response = self.client.get(reverse("dashboard_organisateur"), follow=True)
        self.assertRedirects(response, reverse("connexion"))

    def test_organisateur_desactive_ne_peut_pas_se_reconnecter(self):
        org = creer_organisateur("org_desactive")
        org.is_active = False
        org.save(update_fields=["is_active"])

        reussite = self.client.login(username="org_desactive", password="motdepasse123")
        self.assertFalse(reussite)


class ActivationApresPaiementTests(TestCase):
    """Vérifie le flux complet : inscription libre -> compte inactif par
    défaut -> connexion refusée avec message explicite -> activation
    manuelle par l'admin -> connexion possible."""

    def test_nouveau_compte_organisateur_est_inactif_par_defaut(self):
        url = reverse("inscription_organisateur")

        response = self.client.post(url, {
            "username": "nouvel_organisateur",
            "email": "nouvel_organisateur@test.com",
            "password1": "motdepasse123solide",
            "password2": "motdepasse123solide",
        })

        self.assertRedirects(response, reverse("compte_en_attente"))
        user = User.objects.get(username="nouvel_organisateur")
        self.assertFalse(user.is_active)

    def test_inscription_ne_connecte_pas_automatiquement(self):
        url = reverse("inscription_organisateur")

        self.client.post(url, {
            "username": "nouvel_organisateur",
            "email": "nouvel_organisateur@test.com",
            "password1": "motdepasse123solide",
            "password2": "motdepasse123solide",
        })

        # La session ne doit pas être authentifiée : le compte est inactif
        response = self.client.get(reverse("dashboard_organisateur"))
        self.assertEqual(response.status_code, 302)  # redirigé vers connexion

    def test_connexion_compte_non_active_affiche_message_explicite(self):
        org = creer_organisateur("en_attente")
        org.is_active = False
        org.save(update_fields=["is_active"])

        response = self.client.post(reverse("connexion"), {
            "username": "en_attente",
            "password": "motdepasse123",
        })

        self.assertEqual(response.status_code, 200)  # reste sur la page de connexion
        self.assertContains(response, "pas encore activé")

    def test_apres_activation_admin_connexion_possible(self):
        org = creer_organisateur("futur_actif")
        org.is_active = False
        org.save(update_fields=["is_active"])

        # Simule l'activation manuelle par l'admin
        org.is_active = True
        org.save(update_fields=["is_active"])

        reussite = self.client.login(username="futur_actif", password="motdepasse123")
        self.assertTrue(reussite)
