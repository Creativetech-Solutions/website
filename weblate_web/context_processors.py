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

from django.conf import settings
from django.urls import reverse
from django.utils.translation import override


from weblate_web.data import VERSION, EXTENSIONS, SCREENSHOTS
from weblate_web.models import Donation, Reward
from weblate_web.remote import get_contributors


def weblate_web(request):
    if request.resolver_match and request.resolver_match.url_name:
        match = request.resolver_match
        url_name = ':'.join(match.namespaces + [match.url_name])
        url_kwargs = match.kwargs
    else:
        url_name = 'home'
        url_kwargs = {}

    with override('en'):
        canonical_url = reverse(url_name, kwargs=url_kwargs)

    language_urls = []
    for code, name in settings.LANGUAGES:
        with override(code):
            language_urls.append({
                'name': name,
                'code': code,
                'url': reverse(url_name, kwargs=url_kwargs),
            })

    downloads = [
        'Weblate-{0}.{1}'.format(VERSION, ext) for ext in EXTENSIONS
    ]
    screenshots = [
        {
            'title': title,
            'description': description,
            'image': 'screenshots/{}'.format(filename),
            'thumbnail': 'thumbnails/{}'.format(filename),
        } for filename, description, title in SCREENSHOTS
    ]
    return {
        'downloads': downloads,
        'screenshots': screenshots,
        'canonical_url': canonical_url,
        'language_urls': language_urls,
        'donate_links': Donation.objects.filter(
            active=True, reward__thanks_link=True
        ),
        'rewards': Reward.objects.filter(
            third_party=False, active=True
        ).order_by('amount'),
        'contributors': get_contributors(),
    }
