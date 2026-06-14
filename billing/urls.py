from django.urls import path
from . import views, webhook

app_name = 'billing'

urlpatterns = [
    path('', views.BillingDetailView.as_view(), name='detail'),
    path('webhook/', webhook.bold_webhook, name='bold_webhook'),
]
