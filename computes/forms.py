import re
import json
from django import forms
from django.utils.translation import ugettext_lazy as _
from computes.models import Compute


class ComputeAddTcpForm(forms.Form):
    name = forms.CharField(error_messages={'required': _('No hostname has been entered')},
                           max_length=20)
    hostname = forms.CharField(error_messages={'required': _('No IP / Domain name has been entered')},
                               max_length=100)
    login = forms.CharField(error_messages={'required': _('No login has been entered')},
                            max_length=100)
    password = forms.CharField(error_messages={'required': _('No password has been entered')},
                               max_length=100)
    gstfsd_key = forms.CharField(max_length=256, required=False)


    def clean_name(self):
        name = self.cleaned_data['name']
        have_symbol = re.match('[^a-zA-Z0-9._-]+', name)
        if have_symbol:
            raise forms.ValidationError(_('The host name must not contain any special characters'))
        elif len(name) > 20:
            raise forms.ValidationError(_('The host name must not exceed 20 characters'))
        try:
            Compute.objects.get(name=name)
        except Compute.DoesNotExist:
            return name
        raise forms.ValidationError(_('This host is already connected'))

    def clean_hostname(self):
        hostname = self.cleaned_data['hostname']
        have_symbol = re.match('[^a-z0-9.-]+', hostname)
        wrong_ip = re.match('^0.|^255.', hostname)
        if have_symbol:
            raise forms.ValidationError(_('Hostname must contain only numbers, or the domain name separated by "."'))
        elif wrong_ip:
            raise forms.ValidationError(_('Wrong IP address'))
        try:
            Compute.objects.get(hostname=hostname)
        except Compute.DoesNotExist:
            return hostname
        raise forms.ValidationError(_('This host is already connected'))

    def clean_gstfsd_key(self):
        gstfsd_key = self.cleaned_data['gstfsd_key']
        try:
            data = json.loads(gstfsd_key)
            if not isinstance(data, dict):
                raise forms.ValidationError(_('Gstfsd key must be a json object'))
            if not 'k' in data:
                raise forms.ValidationError(_('Gstfsd key must have a "k" field'))
            if not 'kty' in data:
                raise forms.ValidationError(_('Gstfsd key must have a "kty" field'))
        except ValueError:
            raise forms.ValidationError(_('Gstfsd key must be a valid json'))
        return gstfsd_key


class ComputeAddSshForm(forms.Form):
    name = forms.CharField(error_messages={'required': _('No hostname has been entered')},
                           max_length=20)
    hostname = forms.CharField(error_messages={'required': _('No IP / Domain name has been entered')},
                               max_length=100)
    login = forms.CharField(error_messages={'required': _('No login has been entered')},
                            max_length=20)
    gstfsd_key = forms.CharField(max_length=256, required=False)


    def clean_name(self):
        name = self.cleaned_data['name']
        have_symbol = re.match('[^a-zA-Z0-9._-]+', name)
        if have_symbol:
            raise forms.ValidationError(_('The name of the host must not contain any special characters'))
        elif len(name) > 20:
            raise forms.ValidationError(_('The name of the host must not exceed 20 characters'))
        try:
            Compute.objects.get(name=name)
        except Compute.DoesNotExist:
            return name
        raise forms.ValidationError(_('This host is already connected'))

    def clean_hostname(self):
        hostname = self.cleaned_data['hostname']
        have_symbol = re.match('[^a-zA-Z0-9._-]+', hostname)
        wrong_ip = re.match('^0.|^255.', hostname)
        if have_symbol:
            raise forms.ValidationError(_('Hostname must contain only numbers, or the domain name separated by "."'))
        elif wrong_ip:
            raise forms.ValidationError(_('Wrong IP address'))
        try:
            Compute.objects.get(hostname=hostname)
        except Compute.DoesNotExist:
            return hostname
        raise forms.ValidationError(_('This host is already connected'))

    def clean_gstfsd_key(self):
        gstfsd_key = self.cleaned_data['gstfsd_key']
        try:
            data = json.loads(gstfsd_key)
            if not isinstance(data, dict):
                raise forms.ValidationError(_('Gstfsd key must be a json object'))
            if not 'k' in data:
                raise forms.ValidationError(_('Gstfsd key must have a "k" field'))
            if not 'kty' in data:
                raise forms.ValidationError(_('Gstfsd key must have a "kty" field'))
        except ValueError:
            raise forms.ValidationError(_('Gstfsd key must be a valid json'))
        return gstfsd_key


class ComputeAddTlsForm(forms.Form):
    name = forms.CharField(error_messages={'required': _('No hostname has been entered')},
                           max_length=20)
    hostname = forms.CharField(error_messages={'required': _('No IP / Domain name has been entered')},
                               max_length=100)
    login = forms.CharField(error_messages={'required': _('No login has been entered')},
                            max_length=100)
    password = forms.CharField(error_messages={'required': _('No password has been entered')},
                               max_length=100)
    gstfsd_key = forms.CharField(max_length=256, required=False)


    def clean_name(self):
        name = self.cleaned_data['name']
        have_symbol = re.match('[^a-zA-Z0-9._-]+', name)
        if have_symbol:
            raise forms.ValidationError(_('The host name must not contain any special characters'))
        elif len(name) > 20:
            raise forms.ValidationError(_('The host name must not exceed 20 characters'))
        try:
            Compute.objects.get(name=name)
        except Compute.DoesNotExist:
            return name
        raise forms.ValidationError(_('This host is already connected'))

    def clean_hostname(self):
        hostname = self.cleaned_data['hostname']
        have_symbol = re.match('[^a-z0-9.-]+', hostname)
        wrong_ip = re.match('^0.|^255.', hostname)
        if have_symbol:
            raise forms.ValidationError(_('Hostname must contain only numbers, or the domain name separated by "."'))
        elif wrong_ip:
            raise forms.ValidationError(_('Wrong IP address'))
        try:
            Compute.objects.get(hostname=hostname)
        except Compute.DoesNotExist:
            return hostname
        raise forms.ValidationError(_('This host is already connected'))

    def clean_gstfsd_key(self):
        gstfsd_key = self.cleaned_data['gstfsd_key']
        try:
            data = json.loads(gstfsd_key)
            if not isinstance(data, dict):
                raise forms.ValidationError(_('Gstfsd key must be a json object'))
            if not 'k' in data:
                raise forms.ValidationError(_('Gstfsd key must have a "k" field'))
            if not 'kty' in data:
                raise forms.ValidationError(_('Gstfsd key must have a "kty" field'))
        except ValueError:
            raise forms.ValidationError(_('Gstfsd key must be a valid json'))
        return gstfsd_key


class ComputeEditHostForm(forms.Form):
    host_id = forms.CharField()
    name = forms.CharField(error_messages={'required': _('No hostname has been entered')},
                           max_length=20)
    hostname = forms.CharField(error_messages={'required': _('No IP / Domain name has been entered')},
                               max_length=100)
    login = forms.CharField(error_messages={'required': _('No login has been entered')},
                            max_length=100)
    password = forms.CharField(max_length=100)

    gstfsd_key = forms.CharField(max_length=256, required=False)

    def clean_name(self):
        name = self.cleaned_data['name']
        have_symbol = re.match('[^a-zA-Z0-9._-]+', name)
        if have_symbol:
            raise forms.ValidationError(_('The name of the host must not contain any special characters'))
        elif len(name) > 20:
            raise forms.ValidationError(_('The name of the host must not exceed 20 characters'))
        return name

    def clean_hostname(self):
        hostname = self.cleaned_data['hostname']
        have_symbol = re.match('[^a-zA-Z0-9._-]+', hostname)
        wrong_ip = re.match('^0.|^255.', hostname)
        if have_symbol:
            raise forms.ValidationError(_('Hostname must contain only numbers, or the domain name separated by "."'))
        elif wrong_ip:
            raise forms.ValidationError(_('Wrong IP address'))
        return hostname

    def clean_gstfsd_key(self):
        gstfsd_key = self.cleaned_data['gstfsd_key']
        try:
            data = json.loads(gstfsd_key)
            if not isinstance(data, dict):
                raise forms.ValidationError(_('Gstfsd key must be a json object'))
            if not 'k' in data:
                raise forms.ValidationError(_('Gstfsd key must have a "k" field'))
            if not 'kty' in data:
                raise forms.ValidationError(_('Gstfsd key must have a "kty" field'))
        except ValueError:
            raise forms.ValidationError(_('Gstfsd key must be a valid json'))
        return gstfsd_key


class ComputeAddSocketForm(forms.Form):
    name = forms.CharField(error_messages={'required': _('No hostname has been entered')},
                           max_length=20)

    gstfsd_key = forms.CharField(max_length=256, required=False)


    def clean_name(self):
        name = self.cleaned_data['name']
        have_symbol = re.match('[^a-zA-Z0-9._-]+', name)
        if have_symbol:
            raise forms.ValidationError(_('The host name must not contain any special characters'))
        elif len(name) > 20:
            raise forms.ValidationError(_('The host name must not exceed 20 characters'))
        try:
            Compute.objects.get(name=name)
        except Compute.DoesNotExist:
            return name
        raise forms.ValidationError(_('This host is already connected'))

    def clean_gstfsd_key(self):
        gstfsd_key = self.cleaned_data['gstfsd_key']
        try:
            data = json.loads(gstfsd_key)
            if not isinstance(data, dict):
                raise forms.ValidationError(_('Gstfsd key must be a json object'))
            if not 'k' in data:
                raise forms.ValidationError(_('Gstfsd key must have a "k" field'))
            if not 'kty' in data:
                raise forms.ValidationError(_('Gstfsd key must have a "kty" field'))
        except ValueError:
            raise forms.ValidationError(_('Gstfsd key must be a valid json'))
        return gstfsd_key
