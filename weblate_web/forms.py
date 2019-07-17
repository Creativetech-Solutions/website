# -*- coding: utf-8 -*-
#
# Copyright © 2012 - 2019 Michal Čihař <michal@cihar.com>
#
# This file is part of Weblate <https://weblate.org/>
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.
#

from __future__ import unicode_literals

from django import forms
from wlhosted.payments.backends import list_backends
from wlhosted.payments.models import RECURRENCE_CHOICES

from weblate_web.models import REWARDS, Donation


class SubscribeForm(forms.Form):
    email = forms.EmailField()


class MethodForm(forms.Form):
    method = forms.ChoiceField(
        choices=[],
        required=True,
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['method'].choices = [
            (backend.name, backend.verbose) for backend in list_backends()
        ]


class DonateForm(forms.Form):
    recurring = forms.ChoiceField(
        choices=RECURRENCE_CHOICES,
        initial='',
        required=False,
    )
    amount = forms.IntegerField(
        min_value=5,
        initial=10,
    )
    reward = forms.ChoiceField(
        choices=REWARDS,
        initial=0,
        required=False
    )


class EditLinkForm(forms.ModelForm):
    class Meta:
        model = Donation
        fields = ('link_text', 'link_url')
