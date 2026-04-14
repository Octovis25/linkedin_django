from django import forms
from .models import LinkedinPostPosted

class PostPostedForm(forms.ModelForm):
    class Meta:
        model = LinkedinPostPosted
        fields = ['post_id', 'post_date', 'post_image']
        widgets = {
            'post_id': forms.TextInput(attrs={'placeholder': 'Post-ID', 'class': 'form-control'}),
            'post_date': forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}),
            'post_image': forms.FileInput(attrs={'class': 'form-control'}),
        }
