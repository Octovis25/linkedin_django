from django import forms

class UploadFileForm(forms.Form):
    file = forms.FileField(
        label='Select a file',
        help_text='Upload .xls, .xlsx, or .csv files',
        widget=forms.FileInput(attrs={'class': 'form-control'})
    )
