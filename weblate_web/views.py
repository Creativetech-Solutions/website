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

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError, SuspiciousOperation
from django.core.mail import mail_admins, send_mail
from django.db import transaction
from django.http import JsonResponse, HttpResponse, Http404
from django.shortcuts import redirect, get_object_or_404
from django.urls import reverse
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.utils.translation import ugettext as _
from django.views.generic.edit import FormView, UpdateView
from django.views.generic.dates import ArchiveIndexView
from django.views.generic.detail import DetailView, SingleObjectMixin
from django.views.decorators.http import require_POST

from weblate.utils.django_hacks import monkey_patch_translate

from wlhosted.payments.backends import get_backend, list_backends
from wlhosted.payments.validators import validate_vatin

from wlhosted.payments.models import Payment, Customer
from wlhosted.payments.forms import CustomerForm
from wlhosted.payments.validators import cache_vies_data

from weblate_web.forms import (
    MethodForm, DonateForm, EditLinkForm, SubscribeForm,
)
from weblate_web.models import (
    Donation, Reward, PAYMENTS_ORIGIN, process_payment, Post,
)


@require_POST
def fetch_vat(request):
    if 'payment' not in request.POST or 'vat' not in request.POST:
        raise SuspiciousOperation('Missing needed parameters')
    payment = Payment.objects.filter(
        pk=request.POST['payment'], state=Payment.NEW
    )
    if not payment.exists():
        raise SuspiciousOperation('Already processed payment')
    vat = cache_vies_data(request.POST['vat'])
    return JsonResponse(data=getattr(vat, 'vies_data', {'valid': False}))


class PaymentView(FormView, SingleObjectMixin):
    model = Payment
    form_class = MethodForm
    template_name = 'payment/payment.html'
    check_customer = True

    def redirect_origin(self):
        return redirect(
            '{}?payment={}'.format(
                self.object.customer.origin,
                self.object.pk,
            )
        )

    def get_context_data(self, **kwargs):
        kwargs = super().get_context_data(**kwargs)
        kwargs['can_pay'] = self.can_pay
        kwargs['backends'] = [x(self.object) for x in list_backends()]
        return kwargs

    def validate_customer(self, customer):
        if not self.check_customer:
            return None
        if customer.is_empty:
            messages.info(
                self.request,
                _(
                    'Please provide your billing information to '
                    'complete the payment.'
                )
            )
            return redirect('payment-customer', pk=self.object.pk)
        if customer.vat:
            try:
                validate_vatin(customer.vat)
            except ValidationError:
                messages.warning(
                    self.request,
                    _('The VAT ID is no longer valid, please update it.')
                )
                return redirect('payment-customer', pk=self.object.pk)
        return None

    def dispatch(self, request, *args, **kwargs):
        with transaction.atomic(using='payments_db'):
            self.object = self.get_object()
            customer = self.object.customer
            self.can_pay = not customer.is_empty
            # Redirect already processed payments to origin in case
            # the web redirect was aborted
            if self.object.state != Payment.NEW:
                return self.redirect_origin()
            result = self.validate_customer(customer)
            if result is not None:
                return result
            return super().dispatch(request, *args, **kwargs)

    def form_valid(self, form):
        if not self.can_pay:
            return redirect('payment', pk=self.object.pk)
        # Actualy call the payment backend
        method = form.cleaned_data['method']
        backend = get_backend(method)(self.object)
        result = backend.initiate(
            self.request,
            self.request.build_absolute_uri(
                reverse('payment', kwargs={'pk': self.object.pk})
            ),
            self.request.build_absolute_uri(
                reverse('payment-complete', kwargs={'pk': self.object.pk})
            ),
        )
        if result is not None:
            return result
        backend.complete(self.request)
        return self.redirect_origin()


class CustomerView(PaymentView):
    form_class = CustomerForm
    template_name = 'payment/customer.html'
    check_customer = False

    def form_valid(self, form):
        form.save()
        return redirect('payment', pk=self.object.pk)

    def get_form_kwargs(self):
        """Return the keyword arguments for instantiating the form."""
        kwargs = super().get_form_kwargs()
        kwargs['instance'] = self.object.customer
        return kwargs


class CompleteView(PaymentView):
    def dispatch(self, request, *args, **kwargs):
        with transaction.atomic(using='payments_db'):
            self.object = self.get_object()
            if self.object.state == Payment.NEW:
                return redirect('payment', pk=self.object.pk)
            if self.object.state != Payment.PENDING:
                return self.redirect_origin()

            backend = get_backend(self.object.backend)(self.object)
            backend.complete(self.request)
            return self.redirect_origin()


@method_decorator(login_required, name='dispatch')
class DonateView(FormView):
    form_class = DonateForm
    template_name = 'donate/form.html'
    show_form = True

    def get_form_kwargs(self):
        result = super().get_form_kwargs()
        if 'recurring' in self.request.GET:
            result['initial'] = {'recurring': self.request.GET['recurring']}
        return result

    @staticmethod
    def get_rewards():
        return Reward.objects.filter(
            third_party=False, active=True
        ).order_by('amount')

    def get_context_data(self, **kwargs):
        kwargs = super().get_context_data(**kwargs)
        kwargs['rewards'] = self.get_rewards()
        kwargs['show_form'] = self.show_form
        return kwargs

    def redirect_payment(self, **kwargs):
        kwargs['customer'] = Customer.objects.get_or_create(
            origin=PAYMENTS_ORIGIN,
            user_id=self.request.user.id,
            defaults={
                'email': self.request.user.email,
            }
        )[0]
        payment = Payment.objects.create(**kwargs)
        return redirect(payment.get_payment_url())

    def handle_reward(self, reward):
        return self.redirect_payment(
            amount=reward.amount,
            amount_fixed=True,
            description='Weblate donation: {}'.format(reward.name),
            recurring=reward.recurring,
            extra={
                'reward': str(reward.pk),
            }
        )

    def form_valid(self, form):
        data = form.cleaned_data
        return self.redirect_payment(
            amount=data['amount'],
            amount_fixed=True,
            description='Weblate donation',
            recurring=data['recurring'],
        )

    def post(self, request, *args, **kwargs):
        if 'reward' in request.POST:
            try:
                reward = self.get_rewards().get(pk=int(request.POST['reward']))
                return self.handle_reward(reward)
            except (Reward.DoesNotExist, ValueError):
                pass
        return super().post(request, *args, **kwargs)


class DonateRewardView(DonateView):
    show_form = False

    def get_rewards(self):
        rewards = Reward.objects.filter(pk=self.kwargs['pk'], active=True)
        if not rewards:
            raise Http404('Reward not found')
        return rewards


@login_required
def process_donation(request):
    try:
        payment = Payment.objects.get(
            pk=request.GET['payment'],
            customer__origin=PAYMENTS_ORIGIN,
            customer__user_id=request.user.id
        )
    except (KeyError, Payment.DoesNotExist):
        return redirect(reverse('donate-new'))

    # Create donation
    if payment.state in (Payment.NEW, Payment.PENDING):
        messages.error(
            request,
            _('Payment not yet processed, please retry.')
        )
    elif payment.state == Payment.REJECTED:
        messages.error(
            request,
            _('The payment was rejected: {}').format(
                payment.details.get('reject_reason', _('Unknown reason'))
            )
        )
    elif payment.state == Payment.ACCEPTED:
        messages.success(request, _('Thank you for your donation.'))
        donation = process_payment(payment)
        if donation.reward and donation.reward.has_link:
            return redirect(donation)

    return redirect(reverse('donate'))


@login_required
def download_invoice(request, pk):
    payment = get_object_or_404(
        Payment,
        pk=pk,
        customer__origin=PAYMENTS_ORIGIN,
        customer__user_id=request.user.id
    )

    if not payment.invoice_filename_valid:
        raise Http404(
            'File {0} does not exist!'.format(payment.invoice_filename)
        )

    with open(payment.invoice_full_filename, 'rb') as handle:
        data = handle.read()

    response = HttpResponse(
        data,
        content_type='application/pdf'
    )
    response['Content-Disposition'] = 'attachment; filename={0}'.format(
        payment.invoice_filename
    )
    response['Content-Length'] = len(data)

    return response


@require_POST
@login_required
def disable_repeat(request, pk):
    donation = get_object_or_404(Donation, pk=pk, user=request.user)
    payment = donation.payment_obj
    payment.recurring = ''
    payment.save()
    return redirect(reverse('donate'))


@method_decorator(login_required, name='dispatch')
class EditLinkView(UpdateView):
    form_class = EditLinkForm
    template_name = 'donate/edit.html'
    success_url = '/donate/'

    def get_queryset(self):
        return Donation.objects.filter(
            user=self.request.user,
            reward__has_link=True
        )

    def form_valid(self, form):
        """If the form is valid, save the associated model."""
        mail_admins(
            'Weblate: link changed',
            'New link: {link_url}\nNew text: {link_text}\n'.format(
                **form.cleaned_data
            )
        )
        return super().form_valid(form)


@require_POST
def subscribe(request, name):
    addresses = {
        'hosted': 'hosted-weblate-announce-join@lists.cihar.com',
        'users': 'weblate-join@lists.cihar.com',
    }
    form = SubscribeForm(request.POST)
    if form.is_valid():
        send_mail(
            'subscribe',
            'subscribe',
            form.cleaned_data['email'],
            [addresses[name]],
            fail_silently=True,
        )
        messages.success(
            request,
            _(
                'Subscription was initiated, '
                'you will shortly receive email to confirm it.'
            )
        )
    else:
        messages.error(
            request,
            _('Failed to process subscription request.')
        )

    return redirect('support')


class NewsView(ArchiveIndexView):
    model = Post
    date_field = 'timestamp'
    paginate_by = 10
    ordering = ('-timestamp',)


class PostView(DetailView):
    model = Post

    def get_object(self, queryset=None):
        result = super().get_object(queryset)
        if (not self.request.user.is_superuser
                and result.timestamp >= timezone.now()):
            raise Http404('Future entry')
        return result

    def get_context_data(self, **kwargs):
        kwargs['related'] = Post.objects.filter(
            topic=self.object.topic
        ).exclude(
            pk=self.object.pk
        ).order_by(
            '-timestamp'
        )[:3]
        return kwargs


monkey_patch_translate()
