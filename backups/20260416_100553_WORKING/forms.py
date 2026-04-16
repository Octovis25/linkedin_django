from django import forms
from .models import LinkedinPostPosted

class PostPostedForm(forms.ModelForm):
    upload_image = forms.ImageField(
        required=False,
        label="Post-Bild",
        widget=forms.ClearableFileInput(attrs={"accept": "image/*"})
    )

    class Meta:
        model = LinkedinPostPosted
        fields = ["post_date"]
        widgets = {
            "post_date": forms.DateInput(attrs={
                "type": "date",
                "class": "form-control",
            }),
        }
