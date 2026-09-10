from django import forms
from .models import CustomUser, Course, Subject, Staff, Student


class AddStaffForm(forms.Form):
    first_name = forms.CharField(max_length=100)
    last_name  = forms.CharField(max_length=100)
    email      = forms.EmailField()
    password   = forms.CharField(widget=forms.PasswordInput)
    course     = forms.ModelChoiceField(queryset=Course.objects.all(), required=False)
    address    = forms.CharField(widget=forms.Textarea(attrs={'rows': 3}), required=False)


class EditStaffForm(forms.Form):
    first_name = forms.CharField(max_length=100)
    last_name  = forms.CharField(max_length=100)
    email      = forms.EmailField()
    course     = forms.ModelChoiceField(queryset=Course.objects.all(), required=False)
    address    = forms.CharField(widget=forms.Textarea(attrs={'rows': 3}), required=False)


class AddStudentForm(forms.Form):
    first_name  = forms.CharField(max_length=100)
    last_name   = forms.CharField(max_length=100)
    email       = forms.EmailField()
    password    = forms.CharField(widget=forms.PasswordInput)
    course      = forms.ModelChoiceField(queryset=Course.objects.all(), required=False)
    session     = forms.CharField(max_length=50, required=False,
                                  widget=forms.TextInput(attrs={'placeholder': 'e.g. 2023-24'}))
    roll_no     = forms.CharField(max_length=20, required=False)
    address     = forms.CharField(widget=forms.Textarea(attrs={'rows': 3}), required=False)
    profile_pic = forms.ImageField(required=False,
                                   help_text='Upload a clear front-facing photo for face recognition & attendance')


class EditStudentForm(forms.Form):
    first_name  = forms.CharField(max_length=100)
    last_name   = forms.CharField(max_length=100)
    email       = forms.EmailField()
    course      = forms.ModelChoiceField(queryset=Course.objects.all(), required=False)
    session     = forms.CharField(max_length=50, required=False)
    roll_no     = forms.CharField(max_length=20, required=False)
    address     = forms.CharField(widget=forms.Textarea(attrs={'rows': 3}), required=False)
    profile_pic = forms.ImageField(required=False,
                                   help_text='Upload a new photo to update face recognition')


class CourseForm(forms.ModelForm):
    class Meta:
        model  = Course
        fields = ['name']


class SubjectForm(forms.ModelForm):
    class Meta:
        model  = Subject
        fields = ['name', 'course', 'staff']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['staff'].queryset = CustomUser.objects.filter(
            user_type=CustomUser.STAFF
        )
        self.fields['staff'].label_from_instance = lambda u: u.get_full_name() or u.username
