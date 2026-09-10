from django.urls import include, path

urlpatterns = [path("v1/", include("docai.api.v1.urls"))]
