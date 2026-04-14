from django import forms
from .models import LinkedinPostPosted

class PostPostedForm(forms.ModelForm):
    # Separates Upload-Feld (nicht im Model)
    upload_image = forms.ImageField(
        required=False,
        label="Post-Bild",
        widget=forms.ClearableFileInput(attrs={'accept': 'image/*'})
    )

    class Meta:
        model = LinkedinPostPosted
        fields = ["post_link", "post_date"]
        widgets = {
            "post_link": forms.TextInput(attrs={
                "placeholder": "LinkedIn Post-URL einfuegen...",
                "class": "form-control"
            }),
            "post_date": forms.DateInput(attrs={
                "type": "date",
                "class": "form-control"
            }),
        }
