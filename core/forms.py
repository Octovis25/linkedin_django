from django import forms
from django.contrib.auth.models import User

class CreateUserForm(forms.ModelForm):
    password = forms.CharField(widget=forms.PasswordInput(attrs={"class":"form-input"}), label="Passwort")
    password_confirm = forms.CharField(widget=forms.PasswordInput(attrs={"class":"form-input"}), label="Passwort wiederholen")
    is_superuser = forms.BooleanField(required=False, label="Admin-Rechte (kann User verwalten)")

    class Meta:
        model = User
        fields = ["username", "first_name", "last_name", "email"]
        widgets = {
            "username": forms.TextInput(attrs={"class":"form-input"}),
            "first_name": forms.TextInput(attrs={"class":"form-input"}),
            "last_name": forms.TextInput(attrs={"class":"form-input"}),
            "email": forms.EmailInput(attrs={"class":"form-input"}),
        }
        labels = {"username":"Benutzername","first_name":"Vorname","last_name":"Nachname","email":"E-Mail"}

    def clean(self):
        cd = super().clean()
        if cd.get("password") != cd.get("password_confirm"):
            raise forms.ValidationError("Passwoerter stimmen nicht ueberein!")
        return cd

class EditUserForm(forms.ModelForm):
    new_password = forms.CharField(widget=forms.PasswordInput(attrs={"class":"form-input"}),
        label="Neues Passwort", required=False, help_text="Leer lassen = Passwort bleibt.")
    is_superuser = forms.BooleanField(required=False, label="Admin-Rechte")

    class Meta:
        model = User
        fields = ["username", "first_name", "last_name", "email", "is_active"]
        widgets = {
            "username": forms.TextInput(attrs={"class":"form-input"}),
            "first_name": forms.TextInput(attrs={"class":"form-input"}),
            "last_name": forms.TextInput(attrs={"class":"form-input"}),
            "email": forms.EmailInput(attrs={"class":"form-input"}),
        }
        labels = {"username":"Benutzername","first_name":"Vorname","last_name":"Nachname",
                  "email":"E-Mail","is_active":"Aktiv (kann sich einloggen)"}

class ChangeOwnPasswordForm(forms.Form):
    current_password = forms.CharField(widget=forms.PasswordInput(attrs={"class":"form-input"}), label="Aktuelles Passwort")
    new_password = forms.CharField(widget=forms.PasswordInput(attrs={"class":"form-input"}), label="Neues Passwort")
    new_password_confirm = forms.CharField(widget=forms.PasswordInput(attrs={"class":"form-input"}), label="Neues Passwort wiederholen")

    def clean(self):
        cd = super().clean()
        if cd.get("new_password") != cd.get("new_password_confirm"):
            raise forms.ValidationError("Neue Passwoerter stimmen nicht ueberein!")
        return cd
