"""dhweb URL Configuration

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/2.1/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""

from datetime import datetime

from django.contrib import admin
from django.contrib.flatpages.models import FlatPage
from django.contrib.sitemaps import GenericSitemap, Sitemap
from django.contrib.sitemaps.views import index, sitemap
from django.db.models import QuerySet
from django.urls import include, path, reverse

from abstracts import models


class CoreViewSitemap(Sitemap):
    protocol = "https"
    priority = 0.5
    changefreq = "monthly"

    def items(self):
        return ["home_view", "conference_list", "standalone_conference_list"]

    def location(self, item):
        return reverse(item)


# GenericSitemap expects a Mapping[str, datetime | QuerySet[Model] | str].
# When a dict literal mixes a QuerySet value with a str value (e.g. "date_field"),
# mypy widens the value type to Iterable[object]. Annotating the dict with the
# union type prevents the widening without resorting to Any.
work_sitemap_info: dict[str, datetime | QuerySet[models.Work] | str] = {
    "queryset": models.Work.objects.all(),
    "date_field": "last_updated",
}
author_sitemap_info: dict[str, datetime | QuerySet[models.Author] | str] = {
    "queryset": models.Author.objects.all(),
    "date_field": "last_updated",
}

dh_sitemaps = {
    "sitemaps": {
        "series": GenericSitemap(
            {"queryset": models.ConferenceSeries.objects.all()},
            changefreq="monthly",
            priority=0.8,
            protocol="https",
        ),
        "work": GenericSitemap(
            work_sitemap_info,
            changefreq="monthly",
            priority=1.0,
            protocol="https",
        ),
        "author": GenericSitemap(
            author_sitemap_info,
            changefreq="monthly",
            priority=0.9,
            protocol="https",
        ),
        "flatpages": GenericSitemap(
            {"queryset": FlatPage.objects.all()}, changefreq="monthly", protocol="https"
        ),
        "core": CoreViewSitemap,
    }
}

urlpatterns = [
    path("", include("abstracts.urls")),
    path("admin/", admin.site.urls),
    path("accounts/", include("django.contrib.auth.urls")),
    path("filer/", include("filer.urls")),
    path("pages/", include("django.contrib.flatpages.urls")),
    path("sitemap.xml", index, dh_sitemaps),
    path(
        "sitemap-<section>.xml",
        sitemap,
        dh_sitemaps,
        name="django.contrib.sitemaps.views.sitemap",
    ),
]
