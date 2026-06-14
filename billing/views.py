from django.contrib.auth.mixins import LoginRequiredMixin
from django.shortcuts import render
from django.views import View
from .models import SaaSSubscription


class BillingDetailView(LoginRequiredMixin, View):
    template_name = 'billing/detail.html'

    def get(self, request):
        negocio = request.user.negocios.first()
        sub = getattr(negocio, 'saas_subscription', None) if negocio else None
        payments = sub.payments.all() if sub else []
        return render(request, self.template_name, {
            'negocio': negocio,
            'sub': sub,
            'payments': payments,
        })
