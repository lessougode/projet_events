


"""
Envoi d'email avec template HTML. utils.py
"""
from django.template.loader import render_to_string
from django.core.mail import EmailMessage


def send_email_with_template(subject, template_name, context, to_email: list, from_email, message=None):
    html_message = render_to_string(template_name, context)
    email = EmailMessage(subject, html_message, from_email, to_email)
    email.content_subtype = "html"
    email.send()
    return True

