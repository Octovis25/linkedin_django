from django import forms
from .models import LinkedinPostPosted
class PostPostedForm(forms.ModelForm):
    class Meta:
        model = LinkedinPostPosted
        fields = ["post_link", "post_date"]
        widgets = {"post_link": forms.URLInput(attrs={"class":"form-input","placeholder":"https://www.linkedin.com/feed/update/urn:li:activity:..."}),
            "post_date": forms.DateInput(attrs={"class":"form-input","type":"date"})}
        labels = {"post_link":"LinkedIn Post-Link","post_date":"Tatsaechlich gepostet am"}
        help_texts = {"post_link":"Kompletten Link einfuegen.","post_date":"Wann wurde wirklich gepostet?"}
