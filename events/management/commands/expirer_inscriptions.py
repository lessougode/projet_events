"""
Commande de nettoyage des inscriptions en attente expirées.

À exécuter périodiquement (ex. tâche planifiée toutes les heures) pour que
les inscriptions jamais confirmées après 48h passent au statut EXPIREE.
Cela libère la contrainte d'unicité email+événement, permettant à la
personne de retenter une inscription si elle le souhaite.

Usage :
    python manage.py expirer_inscriptions
"""
from django.core.management.base import BaseCommand
from django.utils import timezone

from events.models import Inscription


class Command(BaseCommand):
    help = "Marque comme EXPIREE les inscriptions EN_ATTENTE dont le délai de 48h est dépassé."

    def handle(self, *args, **options):
        a_expirer = Inscription.objects.filter(
            statut=Inscription.Statut.EN_ATTENTE,
            date_expiration__lt=timezone.now(),
        )
        nombre = a_expirer.count()
        a_expirer.update(statut=Inscription.Statut.EXPIREE)

        if nombre:
            self.stdout.write(self.style.SUCCESS(f"{nombre} inscription(s) marquée(s) comme expirée(s)."))
        else:
            self.stdout.write("Aucune inscription à expirer.")
