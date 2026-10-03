from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import UserCreationForm


class SignupForm(UserCreationForm):
    email = forms.EmailField(
        label="메일 주소",
        required=True,
        widget=forms.EmailInput(attrs={"class": "input", "autocomplete": "email"}),
    )

    class Meta:
        model = get_user_model()
        fields = ("username", "email")

    def clean_email(self):
        email = self.cleaned_data["email"].strip()
        user_model = get_user_model()
        if user_model.objects.filter(email__iexact=email).exists():
            raise forms.ValidationError("이미 가입된 메일 주소입니다.")
        return email

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["username"].label = "사용자명"
        self.fields["username"].widget.attrs.update({"class": "input", "autocomplete": "username"})
        self.fields["password1"].label = "비밀번호"
        self.fields["password1"].widget.attrs.update({"class": "input", "autocomplete": "new-password"})
        self.fields["password2"].label = "비밀번호 확인"
        self.fields["password2"].widget.attrs.update({"class": "input", "autocomplete": "new-password"})
