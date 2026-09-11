from django.urls import include, path, re_path

from docai.api.boundaries import APINotFoundView

urlpatterns = [
    path("<str:version>/", include("docai.api.v1.urls")),
    re_path(r"^.*$", APINotFoundView.as_view(), name="api-not-found"),
]
