from django.urls import path
from categorizer.views import CategorizeTransactionView, HealthCheckView, SampleDataView

urlpatterns = [
    path("categorize/", CategorizeTransactionView.as_view(), name="categorize"),
    path("health/", HealthCheckView.as_view(), name="health"),
    path("samples/", SampleDataView.as_view(), name="samples"),
]
