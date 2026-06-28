import events.models
from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="Evenement",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("titre", models.CharField(max_length=200)),
                ("description", models.TextField(blank=True)),
                ("date_debut", models.DateTimeField(verbose_name="Date de début")),
                ("date_fin", models.DateTimeField(verbose_name="Date de fin")),
                ("lieu", models.CharField(max_length=255)),
                ("places_totales", models.PositiveIntegerField(verbose_name="Nombre de places")),
                ("date_creation", models.DateTimeField(auto_now_add=True)),
                ("organisateur", models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name="evenements",
                    to=settings.AUTH_USER_MODEL,
                    verbose_name="Organisateur",
                )),
            ],
            options={
                "verbose_name": "Événement",
                "verbose_name_plural": "Événements",
                "ordering": ["date_debut"],
            },
        ),
        migrations.CreateModel(
            name="Inscription",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("nom", models.CharField(max_length=150, verbose_name="Nom")),
                ("prenoms", models.CharField(max_length=200, verbose_name="Prénoms")),
                ("telephone1", models.CharField(max_length=30, verbose_name="Téléphone")),
                ("ville", models.CharField(max_length=150, verbose_name="Ville")),
                ("email", models.EmailField(max_length=254, verbose_name="Adresse email")),
                ("statut", models.CharField(
                    choices=[
                        ("EN_ATTENTE", "En attente de confirmation"),
                        ("CONFIRMEE", "Confirmée"),
                        ("EXPIREE", "Expirée"),
                    ],
                    default="EN_ATTENTE",
                    max_length=12,
                )),
                ("token_confirmation", models.CharField(
                    default=events.models.generer_token, editable=False, max_length=64, unique=True
                )),
                ("date_inscription", models.DateTimeField(auto_now_add=True)),
                ("date_expiration", models.DateTimeField(default=events.models.expiration_par_defaut)),
                ("date_confirmation", models.DateTimeField(blank=True, null=True)),
                ("evenement", models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name="inscriptions",
                    to="events.evenement",
                )),
            ],
            options={
                "verbose_name": "Inscription",
                "verbose_name_plural": "Inscriptions",
                "ordering": ["-date_inscription"],
            },
        ),
        migrations.AddConstraint(
            model_name="inscription",
            constraint=models.UniqueConstraint(
                condition=models.Q(("statut__in", ["EN_ATTENTE", "CONFIRMEE"])),
                fields=("evenement", "email"),
                name="unique_email_actif_par_evenement",
            ),
        ),
        migrations.AddConstraint(
            model_name="evenement",
            constraint=models.CheckConstraint(
                condition=models.Q(date_fin__gte=models.F("date_debut")),
                name="date_fin_apres_date_debut",
            ),
        ),
    ]
