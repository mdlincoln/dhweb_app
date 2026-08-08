import json
from datetime import timedelta

from django.conf import settings
from django.test import TestCase
from django.urls import reverse
from django.core.cache import cache
from django.contrib.auth import get_user_model
from django.db import connection
from django.utils import timezone

from abstracts.models import (
    Organizer,
    ConferenceSeries,
    Conference,
    Work,
    Institution,
    Author,
    Authorship,
    Keyword,
    Language,
    Topic,
    Affiliation,
    Country,
    WorkType,
)

from abstracts.forms import WorkFilter

from abstracts.views import PERMISSIONS_ERROR_TEXT


class CachelessTestCase(TestCase):
    """
    Extends the base Django TestCase _setup_and_call method so that it first clears the cache
    """

    def __call__(self, *args, **kwargs):
        cache.clear()
        return super().__call__(*args, **kwargs)


class DefaultCacheBackendTest(TestCase):
    """
    Verifies the default cache backend is Django's built-in PostgreSQL
    DatabaseCache and that it performs a live set/get round trip through the
    django_cache_table.
    """

    def test_default_cache_backend_is_postgres(self):
        self.assertEqual(
            settings.CACHES["default"]["BACKEND"],
            "django.core.cache.backends.db.DatabaseCache",
        )
        self.assertEqual(
            settings.CACHES["default"]["LOCATION"], "django_cache_table"
        )
        self.assertEqual(settings.CACHES["default"]["TIMEOUT"], 600)

    def test_cache_roundtrip_via_database(self):
        cache.set("_dh_cache_roundtrip", "ok", 10)
        self.assertEqual(cache.get("_dh_cache_roundtrip"), "ok")
        cache.delete("_dh_cache_roundtrip")

    def test_cache_never_expires_with_none_timeout(self):
        cache.set("_dh_cache_never", "persist", None)
        self.assertEqual(cache.get("_dh_cache_never"), "persist")
        cache.delete("_dh_cache_never")


class CacheForAnonPostgresTest(TestCase):
    """
    Integration coverage for cache_for_anon page caching on the PostgreSQL
    DatabaseCache backend: anonymous GETs write a django_cache_table row with
    the 10-minute TTL, authenticated GETs write no cache row.
    """

    fixtures = ["test.json"]

    def _cache_page_rows(self):
        key_pattern = cache.make_key(
            "views.decorators.cache.cache_page.%"
        ) + "%"
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT cache_key, expires FROM django_cache_table "
                "WHERE cache_key LIKE %s",
                [key_pattern],
            )
            return cursor.fetchall()

    def test_anonymous_get_writes_cache_row_with_ttl(self):
        cache.clear()
        res = self.client.get(reverse("work_detail", kwargs={"work_id": 1}))
        self.assertEqual(res.status_code, 200)
        rows = self._cache_page_rows()
        self.assertGreaterEqual(len(rows), 1)
        now = timezone.now()
        for _, expires in rows:
            self.assertGreaterEqual(expires, now + timedelta(seconds=590))
            self.assertLessEqual(expires, now + timedelta(seconds=610))

    def test_authenticated_get_writes_no_cache_row(self):
        cache.clear()
        self.client.login(username="root", password="dh-abstracts")
        res = self.client.get(reverse("work_detail", kwargs={"work_id": 1}))
        self.assertEqual(res.status_code, 200)
        self.assertEqual(self._cache_page_rows(), [])


def is_list_unique(x):
    return len(x) == len(set(x))


def publicly_available(testcase, viewname, **kwargs):
    res = testcase.client.get(reverse(viewname, **kwargs))
    testcase.assertEqual(res.status_code, 200)


def privately_available(testcase, viewname, **kwargs):
    target_url = reverse(viewname, **kwargs)
    redirected_url = f"{reverse('login')}?next={target_url}"
    res = testcase.client.get(target_url, follow=True)
    testcase.assertRedirects(res, redirected_url)
    testcase.client.login(username="root", password="dh-abstracts")
    auth_res = testcase.client.get(target_url)
    testcase.assertEqual(auth_res.status_code, 200)


def as_auth(func):
    def auth_client(self):
        self.client.login(username="root", password="dh-abstracts")
        return func(self)

    return auth_client


class EmptyListViewTest(CachelessTestCase):
    """
    Test pages when the database is empty
    """

    def test_home_blank(self):
        publicly_available(self, "home_view")

    def test_work_blank(self):
        publicly_available(self, "work_list")

    def test_author_blank(self):
        publicly_available(self, "author_list")

    def test_conference_blank(self):
        publicly_available(self, "conference_list")


class DownloadPageTest(CachelessTestCase):
    fixtures = ["test.json"]

    def test_render(self):
        publicly_available(self, "download_data")


class AuthorListViewTest(CachelessTestCase):
    """
    Test Author list page
    """

    fixtures = ["test.json"]

    def test_render(self):
        publicly_available(self, "author_list")

    def test_query_total_count(self):
        res = self.client.get(reverse("author_list"))
        self.assertIsInstance(res.context["available_authors_count"], int)

    def test_unique(self):
        res = self.client.get(reverse("author_list"))
        self.assertTrue(is_list_unique(res.context["author_list"]))

    def test_name(self):
        res = self.client.get(reverse("author_list"), data={"name": "rosa"})
        for w in res.context["author_list"]:
            self.assertRegex(w.appellations_index, "Rosalind")

    def test_first_name(self):
        res = self.client.get(reverse("author_list"), data={"name": "rosa"})
        for fn in res.context["author_list"].values_list(
            "authorships__appellation__first_name", flat=True
        ):
            self.assertRegex(fn, "Rosalind")

    def test_last_name(self):
        res = self.client.get(reverse("author_list"), data={"name": "watson"})
        for fn in res.context["author_list"].values_list(
            "authorships__appellation__last_name", flat=True
        ):
            self.assertRegex(fn, "Watson")

    def test_country(self):
        res = self.client.get(reverse("author_list"), data={"country": 1})
        for fn in res.context["author_list"]:
            self.assertIn(
                1,
                Country.objects.filter(
                    institutions__affiliations__asserted_by__author=fn
                ).values_list("id", flat=True),
            )

    def test_institution(self):
        res = self.client.get(reverse("author_list"), data={"institution": 1})
        for fn in res.context["author_list"]:
            self.assertIn(
                1,
                Institution.objects.filter(
                    affiliations__asserted_by__author=fn
                ).values_list("id", flat=True),
            )

    def test_affiliation(self):
        res = self.client.get(reverse("author_list"), data={"affiliation": 1})
        for fn in res.context["author_list"]:
            self.assertIn(
                1,
                Affiliation.objects.filter(asserted_by__author=fn).values_list(
                    "id", flat=True
                ),
            )

    def test_ordering_name_asc(self):
        res = self.client.get(reverse("author_list"), data={"ordering": "last_name"})
        a1 = res.context["author_list"][0]
        a2 = res.context["author_list"][1]
        self.assertLessEqual(
            a1.appellations.all()[0].last_name, a2.appellations.all()[0].last_name
        )

    def test_ordering_name_dsc(self):
        res = self.client.get(reverse("author_list"), data={"ordering": "-last_name"})
        a1 = res.context["author_list"][0]
        a2 = res.context["author_list"][1]
        self.assertGreaterEqual(
            a1.appellations.all()[0].last_name, a2.appellations.all()[0].last_name
        )

    def test_ordering_n_works_asc(self):
        res = self.client.get(reverse("author_list"), data={"ordering": "n_works"})
        a1 = res.context["author_list"][0]
        a2 = res.context["author_list"][1]
        self.assertLessEqual(a1.n_works, a2.n_works)

    def test_ordering_n_works_dsc(self):
        res = self.client.get(reverse("author_list"), data={"ordering": "-n_works"})
        a1 = res.context["author_list"][0]
        a2 = res.context["author_list"][1]
        self.assertGreaterEqual(a1.n_works, a2.n_works)


class InstitutionFullListViewTest(CachelessTestCase):
    """
    Test full Institution list page
    """

    fixtures = ["test.json"]

    def test_render(self):
        privately_available(self, "full_institution_list")

    @as_auth
    def test_query_filtered_count(self):
        res = self.client.get(reverse("full_institution_list"))
        self.assertEqual(
            res.context["filtered_institutions_count"],
            len(res.context["institution_list"]),
        )

    @as_auth
    def test_query_total_count(self):
        res = self.client.get(reverse("full_institution_list"))
        self.assertIsInstance(res.context["available_institutions_count"], int)

    @as_auth
    def test_unique(self):
        res = self.client.get(reverse("full_institution_list"))
        self.assertTrue(is_list_unique(res.context["institution_list"]))

    @as_auth
    def test_sort(self):
        res = self.client.get(reverse("full_institution_list"), data={"ordering": "a"})
        self.assertLess(
            res.context["institution_list"][0].name,
            res.context["institution_list"][1].name,
        )
        res = self.client.get(
            reverse("full_institution_list"), data={"ordering": "n_dsc"}
        )
        self.assertGreaterEqual(
            Authorship.objects.filter(
                affiliations__institution=res.context["institution_list"][0]
            ).count(),
            Authorship.objects.filter(
                affiliations__institution=res.context["institution_list"][1]
            ).count(),
        )
        res = self.client.get(
            reverse("full_institution_list"), data={"ordering": "n_asc"}
        )
        self.assertLessEqual(
            Authorship.objects.filter(
                affiliations__institution=res.context["institution_list"][0]
            ).count(),
            Authorship.objects.filter(
                affiliations__institution=res.context["institution_list"][1]
            ).count(),
        )


class AuthorInstitutionFullListViewTest(CachelessTestCase):
    """
    Test Author-Institution list page
    """

    fixtures = ["test.json"]

    def test_render(self):
        privately_available(self, "author_institution_list")

    @as_auth
    def test_query_filtered_count(self):
        res = self.client.get(reverse("author_institution_list"))
        self.assertEqual(
            res.context["filtered_institutions_count"],
            len(res.context["institution_list"]),
        )

    @as_auth
    def test_query_total_count(self):
        res = self.client.get(reverse("author_institution_list"))
        self.assertIsInstance(res.context["available_institutions_count"], int)

    @as_auth
    def test_unique(self):
        res = self.client.get(reverse("author_institution_list"))
        self.assertTrue(is_list_unique(res.context["institution_list"]))

    @as_auth
    def test_sort(self):
        res = self.client.get(
            reverse("author_institution_list"), data={"ordering": "a"}
        )
        self.assertLess(
            res.context["institution_list"][0].name,
            res.context["institution_list"][1].name,
        )
        res = self.client.get(
            reverse("author_institution_list"), data={"ordering": "n_dsc"}
        )
        self.assertGreaterEqual(
            Authorship.objects.filter(
                affiliations__institution=res.context["institution_list"][0]
            ).count(),
            Authorship.objects.filter(
                affiliations__institution=res.context["institution_list"][1]
            ).count(),
        )
        res = self.client.get(
            reverse("author_institution_list"), data={"ordering": "n_asc"}
        )
        self.assertLessEqual(
            Authorship.objects.filter(
                affiliations__institution=res.context["institution_list"][0]
            ).count(),
            Authorship.objects.filter(
                affiliations__institution=res.context["institution_list"][1]
            ).count(),
        )


class AuthorDetailViewTest(CachelessTestCase):
    """
    Test Author detail page
    """

    fixtures = ["test.json"]

    def test_render(self):
        publicly_available(self, "author_detail", kwargs={"author_id": 1})

    def test_404(self):
        res = self.client.get(reverse("author_detail", kwargs={"author_id": 100}))
        self.assertEqual(res.status_code, 404)

    def test_appellations_unique(self):
        res = self.client.get(reverse("author_detail", kwargs={"author_id": 1}))
        self.assertTrue(is_list_unique([d.id for d in res.context["appellations"]]))

    def test_affiliations_unique_institutions(self):
        res = self.client.get(reverse("author_detail", kwargs={"author_id": 1}))
        self.assertTrue(is_list_unique([d.id for d in res.context["affiliations"]]))


class WorkListViewTest(CachelessTestCase):
    """
    Test Work list page
    """

    fixtures = ["test.json"]

    def test_render(self):
        publicly_available(self, "work_list")

    def test_query_filtered_count(self):
        res = self.client.get(reverse("work_list"))
        self.assertEqual(
            res.context["filtered_works_count"], len(res.context["work_list"])
        )

    def test_query_total_count(self):
        res = self.client.get(reverse("work_list"))
        self.assertIsInstance(res.context["available_works_count"], int)

    def test_form(self):
        res = self.client.get(reverse("work_list"))
        self.assertIsInstance(res.context["work_filter_form"], WorkFilter)

    def test_unique_set(self):
        res = self.client.get(reverse("work_list"))
        self.assertEqual(
            len(set(res.context["work_list"])), res.context["filtered_works_count"]
        )

    def test_search_text(self):
        res = self.client.get(reverse("work_list"), data={"text": "lorem ipsum"})
        all_titles = [w.title for w in res.context["work_list"]]
        self.assertEqual("A Foo Too Far", all_titles[0])
        self.assertTrue(is_list_unique([d.id for d in res.context["work_list"]]))

    def test_search_text_fulltext_weight_b(self):
        # A work whose only hit is in full_text (weight "B") must still be found.
        conf = Conference.objects.first()
        Work.objects.create(
            conference=conf,
            title="Zephyr WeightB Work",
            full_text="This text contains the exceedingly rare token tartarabend only here",
        )
        res = self.client.get(reverse("work_list"), data={"text": "tartarabend"})
        all_titles = [w.title for w in res.context["work_list"]]
        self.assertIn("Zephyr WeightB Work", all_titles)

    def test_ft_available(self):
        res = self.client.get(reverse("work_list"), data={"full_text_available": True})
        self.assertTrue(is_list_unique([d.id for d in res.context["work_list"]]))
        for w in res.context["work_list"]:
            self.assertTrue(w.full_text != "")

    def test_work_type(self):
        res = self.client.get(reverse("work_list"), data={"work_type": 1})
        self.assertTrue(is_list_unique([d.id for d in res.context["work_list"]]))
        for w in res.context["work_list"]:
            self.assertEqual(w.work_type.id, 1)

    def test_conference(self):
        res = self.client.get(reverse("work_list"), data={"conference": 1})
        self.assertTrue(is_list_unique([d.id for d in res.context["work_list"]]))
        for w in res.context["work_list"]:
            self.assertEqual(w.conference.id, 1)

    def test_institution(self):
        res = self.client.get(reverse("work_list"), data={"institution": 2})
        self.assertTrue(is_list_unique([d.id for d in res.context["work_list"]]))
        for w in res.context["work_list"]:
            all_institutions = Institution.objects.filter(
                affiliations__asserted_by__work=w.id
            ).values_list("id", flat=True)
            self.assertIn(2, all_institutions)

    def test_keyword(self):
        res = self.client.get(reverse("work_list"), data={"keywords": 1})
        self.assertTrue(is_list_unique([d.id for d in res.context["work_list"]]))
        for w in res.context["work_list"]:
            self.assertIn(1, w.keywords.values_list("id", flat=True))

    def test_topic(self):
        res = self.client.get(reverse("work_list"), data={"topics": 1})
        self.assertTrue(is_list_unique([d.id for d in res.context["work_list"]]))
        for w in res.context["work_list"]:
            self.assertIn(1, w.topics.values_list("id", flat=True))

    def test_language(self):
        res = self.client.get(reverse("work_list"), data={"languages": 1})
        self.assertTrue(is_list_unique([d.id for d in res.context["work_list"]]))
        for w in res.context["work_list"]:
            self.assertIn(1, w.languages.values_list("id", flat=True))

    def test_author(self):
        res = self.client.get(reverse("work_list"), data={"author": 1})
        self.assertTrue(is_list_unique([d.id for d in res.context["work_list"]]))
        for w in res.context["work_list"]:
            self.assertIn(
                1, Author.objects.filter(works=w).values_list("id", flat=True)
            )

    def test_ordering_year_asc(self):
        res = self.client.get(reverse("work_list"), data={"ordering": "year"})
        self.assertTrue(is_list_unique([d.id for d in res.context["work_list"]]))
        a1 = res.context["work_list"][0]
        a2 = res.context["work_list"][1]
        self.assertLessEqual(a1.conference.year, a2.conference.year)

    def test_ordering_year_dsc(self):
        res = self.client.get(reverse("work_list"), data={"ordering": "-year"})
        self.assertTrue(is_list_unique([d.id for d in res.context["work_list"]]))
        a1 = res.context["work_list"][0]
        a2 = res.context["work_list"][1]
        self.assertGreaterEqual(a1.conference.year, a2.conference.year)

    def test_ordering_title_asc(self):
        res = self.client.get(reverse("work_list"), data={"ordering": "title"})
        self.assertTrue(is_list_unique([d.id for d in res.context["work_list"]]))
        a1 = res.context["work_list"][0]
        a2 = res.context["work_list"][1]
        self.assertLessEqual(a1.title.lower(), a2.title.lower())

    def test_ordering_title_dsc(self):
        res = self.client.get(reverse("work_list"), data={"ordering": "-title"})
        self.assertTrue(is_list_unique([d.id for d in res.context["work_list"]]))
        a1 = res.context["work_list"][0]
        a2 = res.context["work_list"][1]
        self.assertGreaterEqual(a1.title.lower(), a2.title.lower())

    def test_ordering_name_asc(self):
        res = self.client.get(reverse("work_list"), data={"ordering": "last_name"})
        self.assertTrue(is_list_unique([d.id for d in res.context["work_list"]]))
        a1 = res.context["work_list"][0]
        a2 = res.context["work_list"][1]
        self.assertLessEqual(
            a1.authorships.order_by("authorship_order").first().appellation.last_name,
            a2.authorships.order_by("authorship_order").first().appellation.last_name,
        )

    def test_ordering_name_dsc(self):
        res = self.client.get(reverse("work_list"), data={"ordering": "-last_name"})
        self.assertTrue(is_list_unique([d.id for d in res.context["work_list"]]))
        a1 = res.context["work_list"][0]
        a2 = res.context["work_list"][1]
        self.assertGreaterEqual(
            a1.authorships.order_by("authorship_order").first().appellation.last_name,
            a2.authorships.order_by("authorship_order").first().appellation.last_name,
        )


class WorkDetailViewTest(CachelessTestCase):
    """
    Test Work detail view
    """

    fixtures = ["test.json"]

    def test_render(self):
        publicly_available(self, "work_detail", kwargs={"work_id": 1})

    def test_404(self):
        res = self.client.get(reverse("work_detail", kwargs={"work_id": 100}))
        self.assertEqual(res.status_code, 404)

    def test_is_work(self):
        res = self.client.get(reverse("work_detail", kwargs={"work_id": 1}))
        self.assertIsInstance(res.context["work"], Work)

    def test_authorships_unique(self):
        res = self.client.get(reverse("work_detail", kwargs={"work_id": 1}))
        self.assertTrue(is_list_unique(res.context["authorships"]))

    def test_hide_private_full_text(self):
        res = self.client.get(reverse("work_detail", kwargs={"work_id": 3}))
        self.assertContains(res, "cannot display")

    def test_show_public_full_text(self):
        res = self.client.get(reverse("work_detail", kwargs={"work_id": 1}))
        self.assertContains(res, "Lorem Ipsum Dolor")


class ConferenceSeriesListViewTest(CachelessTestCase):
    """
    Test Conference Series list view
    """

    fixtures = ["test.json"]

    def test_render(self):
        publicly_available(self, "conference_list")

    def test_unique(self):
        res = self.client.get(reverse("conference_list"))
        self.assertTrue(is_list_unique(res.context["series_list"]))


class ConferenceSeriesDetailView(CachelessTestCase):
    """
    Test Conference Series list view
    """

    fixtures = ["test.json"]

    def test_render(self):
        publicly_available(self, "conference_series_detail", kwargs={"pk": 1})

    def test_unique(self):
        res = self.client.get(reverse("conference_series_detail", kwargs={"pk": 1}))
        self.assertTrue(is_list_unique(res.context["conference_list"]))
        self.assertTrue(is_list_unique(res.context["series_list"]))


class AuthorMergeViewTest(CachelessTestCase):
    fixtures = ["test.json"]

    def test_render(self):
        privately_available(self, "author_merge", kwargs={"author_id": 1})

    @as_auth
    def test_404(self):
        res = self.client.get(
            reverse("author_merge", kwargs={"author_id": 100}), follow=True
        )
        self.assertEqual(res.status_code, 404)

    @as_auth
    def test_post(self):
        res = self.client.post(
            reverse("author_merge", kwargs={"author_id": 1}),
            data={"into": 2},
            follow=True,
        )
        expected_redirect = reverse("author_detail", kwargs={"author_id": 2})
        self.assertRedirects(res, expected_redirect)
        self.assertFalse(Author.objects.filter(pk=1).exists())
        self.assertContains(res, "updated")
        self.assertContains(res, "deleted")

    @as_auth
    def test_invalid_author(self):
        res = self.client.post(
            reverse("author_merge", kwargs={"author_id": 1}),
            data={"into": 1},
            follow=True,
        )
        expected_redirect = reverse("author_merge", kwargs={"author_id": 1})
        self.assertRedirects(res, expected_redirect)
        self.assertContains(res, "You cannot merge an author into themselves")


class InstitutionMergeViewTest(CachelessTestCase):
    fixtures = ["test.json"]

    def test_render(self):
        privately_available(self, "institution_merge", kwargs={"institution_id": 1})

    @as_auth
    def test_404(self):
        res = self.client.get(
            reverse("institution_merge", kwargs={"institution_id": 100}), follow=True
        )
        self.assertEqual(res.status_code, 404)

    @as_auth
    def test_post(self):
        res = self.client.post(
            reverse("institution_merge", kwargs={"institution_id": 1}),
            data={"into": 2},
            follow=True,
        )
        expected_redirect = reverse("institution_edit", kwargs={"pk": 2})
        self.assertRedirects(res, expected_redirect)
        self.assertFalse(Institution.objects.filter(pk=1).exists())
        self.assertContains(res, "updated")

    @as_auth
    def test_invalid_institution(self):
        res = self.client.post(
            reverse("institution_merge", kwargs={"institution_id": 1}),
            data={"into": 1},
            follow=True,
        )
        expected_redirect = reverse("institution_merge", kwargs={"institution_id": 1})
        self.assertRedirects(res, expected_redirect)
        self.assertContains(res, "You cannot merge an institution into itself")


class AffiliationMergeViewTest(CachelessTestCase):
    fixtures = ["test.json"]

    def test_render(self):
        privately_available(self, "affiliation_merge", kwargs={"affiliation_id": 1})

    @as_auth
    def test_404(self):
        res = self.client.get(
            reverse("affiliation_merge", kwargs={"affiliation_id": 100}), follow=True
        )
        self.assertEqual(res.status_code, 404)

    @as_auth
    def test_post(self):
        res = self.client.post(
            reverse("affiliation_merge", kwargs={"affiliation_id": 1}),
            data={"into": 2},
            follow=True,
        )
        expected_redirect = reverse("affiliation_edit", kwargs={"pk": 2})
        self.assertRedirects(res, expected_redirect)
        self.assertFalse(Affiliation.objects.filter(pk=1).exists())
        self.assertContains(res, "updated")

    @as_auth
    def test_invalid_affiliation(self):
        res = self.client.post(
            reverse("affiliation_merge", kwargs={"affiliation_id": 1}),
            data={"into": 1},
            follow=True,
        )
        expected_redirect = reverse("affiliation_merge", kwargs={"affiliation_id": 1})
        self.assertRedirects(res, expected_redirect)
        self.assertContains(res, "You cannot merge an affiliation into itself")


class AffiliationMultiMergeViewTest(CachelessTestCase):
    fixtures = ["test.json"]

    def test_render(self):
        privately_available(self, "affiliation_multi_merge")

    @as_auth
    def test_post(self):
        res = self.client.post(
            reverse("affiliation_multi_merge"),
            data={"sources": [1, 3, 4], "into": 2},
            follow=True,
        )
        expected_redirect = reverse("affiliation_edit", kwargs={"pk": 2})
        self.assertRedirects(res, expected_redirect)
        self.assertFalse(Affiliation.objects.filter(pk=1).exists())
        self.assertTrue(Affiliation.objects.filter(pk=2).exists())
        self.assertFalse(Affiliation.objects.filter(pk=3).exists())
        self.assertFalse(Affiliation.objects.filter(pk=4).exists())
        self.assertContains(res, "updated")


class InstitutionMultiMergeViewTest(CachelessTestCase):
    fixtures = ["test.json"]

    def test_render(self):
        privately_available(self, "institution_multi_merge")

    @as_auth
    def test_post(self):
        res = self.client.post(
            reverse("institution_multi_merge"),
            data={"sources": [1, 3], "into": 2},
            follow=True,
        )
        expected_redirect = reverse("institution_edit", kwargs={"pk": 2})
        self.assertRedirects(res, expected_redirect)
        self.assertFalse(Institution.objects.filter(pk=1).exists())
        self.assertTrue(Institution.objects.filter(pk=2).exists())
        self.assertFalse(Institution.objects.filter(pk=3).exists())
        self.assertContains(res, "updated")


class WipeUnusedViewTest(CachelessTestCase):
    fixtures = ["test.json"]

    def test_render(self):
        privately_available(self, "wipe_unused")

    @as_auth
    def test_has_dict(self):
        res = self.client.get(reverse("wipe_unused"))
        self.assertIsInstance(res.context["deletions"], dict)
        self.assertIsInstance(res.context["hanging_items"], bool)
        self.assertTrue(res.context["hanging_items"])

    @as_auth
    def test_post(self):
        res = self.client.post(reverse("wipe_unused"))
        res = self.client.post(reverse("wipe_unused"))
        self.assertFalse(res.context["hanging_items"])


class CreateConferenceViewTest(CachelessTestCase):
    fixtures = ["test.json"]

    def test_render(self):
        privately_available(self, "conference_create")

    @as_auth
    def test_post(self):
        res = self.client.post(
            reverse("conference_create"),
            data={
                "year": 1987,
                "short_title": "foo",
                "notes": "buzz",
                "organizers": [1, 2],
            },
            follow=True,
        )
        self.assertContains(res, "created")


class EditConferenceViewTest(CachelessTestCase):
    fixtures = ["test.json"]

    def test_render(self):
        privately_available(self, "conference_edit", kwargs={"pk": 1})

    @as_auth
    def test_post(self):
        res = self.client.post(
            reverse("conference_edit", kwargs={"pk": 1}),
            data={
                "year": "1987",
                "short_title": "foo",
                "notes": "buzz",
                "organizers": ["1"],
                "form-0-number": [""],
                "form-0-series": ["1"],
                "form-INITIAL_FORMS": ["1"],
                "form-MAX_NUM_FORMS": ["1000"],
                "form-MIN_NUM_FORMS": ["0"],
                "form-TOTAL_FORMS": ["1"],
            },
            follow=True,
        )
        self.assertContains(res, "updated")


class DeleteConferenceViewTest(CachelessTestCase):
    fixtures = ["test.json"]

    def test_render(self):
        privately_available(self, "conference_delete", kwargs={"pk": 1})

    @as_auth
    def test_post(self):
        res = self.client.post(
            reverse("conference_delete", kwargs={"pk": 1}), follow=True
        )
        self.assertContains(res, "deleted")
        self.assertFalse(Conference.objects.filter(pk=1).exists())


class CreateSeriesViewTest(CachelessTestCase):
    fixtures = ["test.json"]

    def test_render(self):
        privately_available(self, "series_create")

    @as_auth
    def test_post(self):
        res = self.client.post(
            reverse("series_create"),
            data={"title": "foo", "abbreviation": "bar", "notes": "buzz"},
            follow=True,
        )
        self.assertContains(res, "created")


class EditSeriesViewTest(CachelessTestCase):
    fixtures = ["test.json"]

    def test_render(self):
        privately_available(self, "series_edit", kwargs={"pk": 1})

    @as_auth
    def test_post(self):
        res = self.client.post(
            reverse("series_edit", kwargs={"pk": 1}),
            data={"title": "fi", "abbreviation": "fi", "notes": "buzz"},
            follow=True,
        )
        self.assertContains(res, "updated")


class DeleteSeriesViewTest(CachelessTestCase):
    fixtures = ["test.json"]

    def test_render(self):
        privately_available(self, "series_delete", kwargs={"pk": 1})

    @as_auth
    def test_post(self):
        res = self.client.post(reverse("series_delete", kwargs={"pk": 1}), follow=True)
        self.assertContains(res, "deleted")
        self.assertFalse(ConferenceSeries.objects.filter(pk=1).exists())


class OrganizerListViewTest(CachelessTestCase):
    fixtures = ["test.json"]

    def test_render(self):
        privately_available(self, "full_organizer_list")

    @as_auth
    def test_unique(self):
        res = self.client.get(reverse("full_organizer_list"))
        self.assertTrue(is_list_unique(res.context["organizer_list"]))


class CreateOrganizerViewTest(CachelessTestCase):
    fixtures = ["test.json"]

    def test_render(self):
        privately_available(self, "organizer_create")

    @as_auth
    def test_post(self):
        res = self.client.post(
            reverse("organizer_create"),
            data={"title": "foo", "abbreviation": "bar", "notes": "buzz"},
            follow=True,
        )
        self.assertContains(res, "created")


class EditOrganizerViewTest(CachelessTestCase):
    fixtures = ["test.json"]

    def test_render(self):
        privately_available(self, "organizer_edit", kwargs={"pk": 1})

    @as_auth
    def test_post(self):
        res = self.client.post(
            reverse("organizer_edit", kwargs={"pk": 1}),
            data={"title": "foo", "abbreviation": "bar", "notes": "buzz"},
            follow=True,
        )
        self.assertEqual(res.status_code, 200)


class DeleteOrganizerViewTest(CachelessTestCase):
    fixtures = ["test.json"]

    def test_render(self):
        privately_available(self, "organizer_delete", kwargs={"pk": 1})

    @as_auth
    def test_post(self):
        res = self.client.post(
            reverse("organizer_delete", kwargs={"pk": 1}), follow=True
        )
        self.assertContains(res, "deleted")
        self.assertFalse(Organizer.objects.filter(pk=1).exists())


class DeleteWorkViewTest(CachelessTestCase):
    fixtures = ["test.json"]

    def test_render(self):
        privately_available(self, "work_delete", kwargs={"pk": 1})

    @as_auth
    def test_post(self):
        self.client.post(reverse("work_delete", kwargs={"pk": 1}), follow=True)
        self.assertFalse(Work.objects.filter(pk=1).exists())


class AuthorJSONViewTest(CachelessTestCase):
    fixtures = ["test.json"]

    def test_render(self):
        privately_available(self, "author-info-json", kwargs={"author_id": 1})

    @as_auth
    def test_format(self):
        res = self.client.get(reverse("author-info-json", kwargs={"author_id": 1}))
        self.assertTrue("first_name" in json.dumps(str(res.content)))
        self.assertTrue("last_name" in json.dumps(str(res.content)))
        self.assertTrue("affiliation" in json.dumps(str(res.content)))


class AffiliationJSONViewTest(CachelessTestCase):
    fixtures = ["test.json"]

    def test_render(self):
        privately_available(self, "affiliation-info-json", kwargs={"affiliation_id": 1})

    @as_auth
    def test_format(self):
        res = self.client.get(
            reverse("affiliation-info-json", kwargs={"affiliation_id": 1})
        )
        self.assertTrue("department" in json.dumps(str(res.content)))
        self.assertTrue("institution" in json.dumps(str(res.content)))


class KeywordFullListViewTest(CachelessTestCase):
    """
    Test full Keyword list page
    """

    fixtures = ["test.json"]

    def test_render(self):
        privately_available(self, "full_keyword_list")

    @as_auth
    def test_query_filtered_count(self):
        res = self.client.get(reverse("full_keyword_list"))
        self.assertEqual(
            res.context["filtered_tags_count"], len(res.context["tag_list"])
        )

    @as_auth
    def test_query_total_count(self):
        res = self.client.get(reverse("full_keyword_list"))
        self.assertIsInstance(res.context["available_tags_count"], int)

    @as_auth
    def test_unique(self):
        res = self.client.get(reverse("full_keyword_list"))
        self.assertTrue(is_list_unique(res.context["tag_list"]))

    @as_auth
    def test_sort(self):
        res = self.client.get(reverse("full_keyword_list"), data={"ordering": "a"})
        self.assertTrue(res.context["tag_list"].ordered)
        res = self.client.get(reverse("full_keyword_list"), data={"ordering": "n_dsc"})
        self.assertTrue(res.context["tag_list"].ordered)
        res = self.client.get(reverse("full_keyword_list"), data={"ordering": "n_asc"})
        self.assertTrue(res.context["tag_list"].ordered)


class CreateKeywordViewTest(CachelessTestCase):
    fixtures = ["test.json"]

    def test_render(self):
        privately_available(self, "keyword_create")

    @as_auth
    def test_post(self):
        res = self.client.post(
            reverse("keyword_create"), data={"title": "foo"}, follow=True
        )
        self.assertContains(res, "created")
        self.assertTrue(Keyword.objects.filter(title="foo").exists())


class EditKeywordViewTest(CachelessTestCase):
    fixtures = ["test.json"]

    def test_render(self):
        privately_available(self, "keyword_edit", kwargs={"pk": 1})

    @as_auth
    def test_post(self):
        res = self.client.post(
            reverse("keyword_edit", kwargs={"pk": 1}),
            data={"title": "buzz"},
            follow=True,
        )
        self.assertContains(res, "updated")
        self.assertTrue(Keyword.objects.filter(title="buzz").exists())


class DeleteKeywordViewTest(CachelessTestCase):
    fixtures = ["test.json"]

    def test_render(self):
        privately_available(self, "keyword_delete", kwargs={"pk": 1})

    @as_auth
    def test_post(self):
        self.client.post(reverse("keyword_delete", kwargs={"pk": 1}), follow=True)
        self.assertFalse(Keyword.objects.filter(pk=1).exists())


class KeywordMergeViewTest(CachelessTestCase):
    fixtures = ["test.json"]

    def test_render(self):
        privately_available(self, "keyword_merge", kwargs={"keyword_id": 1})

    @as_auth
    def test_404(self):
        res = self.client.get(
            reverse("keyword_merge", kwargs={"keyword_id": 100}), follow=True
        )
        self.assertEqual(res.status_code, 404)

    @as_auth
    def test_post(self):
        res = self.client.post(
            reverse("keyword_merge", kwargs={"keyword_id": 1}),
            data={"into": 2},
            follow=True,
        )
        expected_redirect = reverse("keyword_edit", kwargs={"pk": 2})
        self.assertRedirects(res, expected_redirect)
        self.assertFalse(Keyword.objects.filter(pk=1).exists())
        self.assertContains(res, "updated")
        self.assertContains(res, "deleted")

    @as_auth
    def test_invalid_keyword(self):
        res = self.client.post(
            reverse("keyword_merge", kwargs={"keyword_id": 1}),
            data={"into": 1},
            follow=True,
        )
        expected_redirect = reverse("keyword_merge", kwargs={"keyword_id": 1})
        self.assertRedirects(res, expected_redirect)
        self.assertContains(res, "You cannot merge a keyword into itself")


class KeywordMultiMergeViewTest(CachelessTestCase):
    fixtures = ["test.json"]

    def test_render(self):
        privately_available(self, "keyword_multi_merge")

    @as_auth
    def test_post(self):
        res = self.client.post(
            reverse("keyword_multi_merge"),
            data={"sources": [1, 3, 4], "into": 2},
            follow=True,
        )
        expected_redirect = reverse("keyword_edit", kwargs={"pk": 2})
        self.assertRedirects(res, expected_redirect)
        self.assertFalse(Keyword.objects.filter(pk=1).exists())
        self.assertTrue(Keyword.objects.filter(pk=2).exists())
        self.assertFalse(Keyword.objects.filter(pk=3).exists())
        self.assertFalse(Keyword.objects.filter(pk=4).exists())
        self.assertContains(res, "updated")
        self.assertContains(res, "deleted")


class TopicFullListViewTest(CachelessTestCase):
    """
    Test full Topic list page
    """

    fixtures = ["test.json"]

    def test_render(self):
        privately_available(self, "full_topic_list")

    @as_auth
    def test_query_filtered_count(self):
        res = self.client.get(reverse("full_topic_list"))
        self.assertEqual(
            res.context["filtered_tags_count"], len(res.context["tag_list"])
        )

    @as_auth
    def test_query_total_count(self):
        res = self.client.get(reverse("full_topic_list"))
        self.assertIsInstance(res.context["available_tags_count"], int)

    @as_auth
    def test_unique(self):
        res = self.client.get(reverse("full_topic_list"))
        self.assertTrue(is_list_unique(res.context["tag_list"]))


class CreateTopicViewTest(CachelessTestCase):
    fixtures = ["test.json"]

    def test_render(self):
        privately_available(self, "topic_create")

    @as_auth
    def test_post(self):
        res = self.client.post(
            reverse("topic_create"), data={"title": "foo"}, follow=True
        )
        self.assertContains(res, "created")
        self.assertTrue(Topic.objects.filter(title="foo").exists())


class EditTopicViewTest(CachelessTestCase):
    fixtures = ["test.json"]

    def test_render(self):
        privately_available(self, "topic_edit", kwargs={"pk": 1})

    @as_auth
    def test_post(self):
        res = self.client.post(
            reverse("topic_edit", kwargs={"pk": 1}), data={"title": "buzz"}, follow=True
        )
        self.assertContains(res, "updated")
        self.assertTrue(Topic.objects.filter(title="buzz").exists())


class DeleteTopicViewTest(CachelessTestCase):
    fixtures = ["test.json"]

    def test_render(self):
        privately_available(self, "topic_delete", kwargs={"pk": 1})

    @as_auth
    def test_post(self):
        self.client.post(reverse("topic_delete", kwargs={"pk": 1}), follow=True)
        self.assertFalse(Topic.objects.filter(pk=1).exists())


class TopicMultiMergeViewTest(CachelessTestCase):
    fixtures = ["test.json"]

    def test_render(self):
        privately_available(self, "topic_multi_merge")

    @as_auth
    def test_post(self):
        res = self.client.post(
            reverse("topic_multi_merge"),
            data={"sources": [1, 3, 4], "into": 2},
            follow=True,
        )
        expected_redirect = reverse("topic_edit", kwargs={"pk": 2})
        self.assertRedirects(res, expected_redirect)
        self.assertFalse(Topic.objects.filter(pk=1).exists())
        self.assertTrue(Topic.objects.filter(pk=2).exists())
        self.assertFalse(Topic.objects.filter(pk=3).exists())
        self.assertFalse(Topic.objects.filter(pk=4).exists())
        self.assertContains(res, "updated")
        self.assertContains(res, "deleted")


class LanguageFullListViewTest(CachelessTestCase):
    """
    Test full Language list page
    """

    fixtures = ["test.json"]

    def test_render(self):
        privately_available(self, "full_language_list")

    @as_auth
    def test_query_filtered_count(self):
        res = self.client.get(reverse("full_language_list"))
        self.assertEqual(
            res.context["filtered_tags_count"], len(res.context["tag_list"])
        )

    @as_auth
    def test_query_total_count(self):
        res = self.client.get(reverse("full_language_list"))
        self.assertIsInstance(res.context["available_tags_count"], int)

    @as_auth
    def test_unique(self):
        res = self.client.get(reverse("full_language_list"))
        self.assertTrue(is_list_unique(res.context["tag_list"]))

    @as_auth
    def test_sort(self):
        res = self.client.get(reverse("full_language_list"), data={"ordering": "a"})
        self.assertTrue(res.context["tag_list"].ordered)
        res = self.client.get(reverse("full_language_list"), data={"ordering": "n_dsc"})
        self.assertTrue(res.context["tag_list"].ordered)
        res = self.client.get(reverse("full_language_list"), data={"ordering": "n_asc"})
        self.assertTrue(res.context["tag_list"].ordered)


class CreateLanguageViewTest(CachelessTestCase):
    fixtures = ["test.json"]

    def test_render(self):
        privately_available(self, "language_create")

    @as_auth
    def test_post(self):
        res = self.client.post(
            reverse("language_create"), data={"title": "foo"}, follow=True
        )
        self.assertContains(res, "created")
        self.assertTrue(Language.objects.filter(title="foo").exists())


class EditLanguageViewTest(CachelessTestCase):
    fixtures = ["test.json"]

    def test_render(self):
        privately_available(self, "language_edit", kwargs={"pk": 1})

    @as_auth
    def test_post(self):
        res = self.client.post(
            reverse("language_edit", kwargs={"pk": 1}),
            data={"title": "buzz"},
            follow=True,
        )
        self.assertContains(res, "updated")
        self.assertTrue(Language.objects.filter(title="buzz").exists())


class DeleteLanguageViewTest(CachelessTestCase):
    fixtures = ["test.json"]

    def test_render(self):
        privately_available(self, "language_delete", kwargs={"pk": 1})

    @as_auth
    def test_post(self):
        self.client.post(reverse("language_delete", kwargs={"pk": 1}), follow=True)
        self.assertFalse(Language.objects.filter(pk=1).exists())


class LanguageMergeViewTest(CachelessTestCase):
    fixtures = ["test.json"]

    def test_render(self):
        privately_available(self, "language_merge", kwargs={"language_id": 1})

    @as_auth
    def test_404(self):
        res = self.client.get(
            reverse("language_merge", kwargs={"language_id": 100}), follow=True
        )
        self.assertEqual(res.status_code, 404)

    @as_auth
    def test_post(self):
        res = self.client.post(
            reverse("language_merge", kwargs={"language_id": 1}),
            data={"into": 2},
            follow=True,
        )
        expected_redirect = reverse("language_edit", kwargs={"pk": 2})
        self.assertRedirects(res, expected_redirect)
        self.assertFalse(Language.objects.filter(pk=1).exists())
        self.assertContains(res, "updated")
        self.assertContains(res, "deleted")

    @as_auth
    def test_invalid_language(self):
        res = self.client.post(
            reverse("language_merge", kwargs={"language_id": 1}),
            data={"into": 1},
            follow=True,
        )
        expected_redirect = reverse("language_merge", kwargs={"language_id": 1})
        self.assertRedirects(res, expected_redirect)
        self.assertContains(res, "You cannot merge a language into itself")


class WorkTypeFullListViewTest(CachelessTestCase):
    """
    Test full WorkType list page
    """

    fixtures = ["test.json"]

    def test_render(self):
        privately_available(self, "full_work_type_list")

    @as_auth
    def test_query_filtered_count(self):
        res = self.client.get(reverse("full_work_type_list"))
        self.assertEqual(
            res.context["filtered_tags_count"], len(res.context["tag_list"])
        )

    @as_auth
    def test_query_total_count(self):
        res = self.client.get(reverse("full_work_type_list"))
        self.assertIsInstance(res.context["available_tags_count"], int)

    @as_auth
    def test_unique(self):
        res = self.client.get(reverse("full_work_type_list"))
        self.assertTrue(is_list_unique(res.context["tag_list"]))

    @as_auth
    def test_sort(self):
        res = self.client.get(reverse("full_work_type_list"), data={"ordering": "a"})
        self.assertTrue(res.context["tag_list"].ordered)
        res = self.client.get(
            reverse("full_work_type_list"), data={"ordering": "n_dsc"}
        )
        self.assertTrue(res.context["tag_list"].ordered)
        res = self.client.get(
            reverse("full_work_type_list"), data={"ordering": "n_asc"}
        )
        self.assertTrue(res.context["tag_list"].ordered)


class CreateWorkTypeViewTest(CachelessTestCase):
    fixtures = ["test.json"]

    def test_render(self):
        privately_available(self, "work_type_create")

    @as_auth
    def test_post(self):
        res = self.client.post(
            reverse("work_type_create"), data={"title": "foo"}, follow=True
        )
        self.assertContains(res, "created")
        self.assertTrue(WorkType.objects.filter(title="foo").exists())


class EditWorkTypeViewTest(CachelessTestCase):
    fixtures = ["test.json"]

    def test_render(self):
        privately_available(self, "work_type_edit", kwargs={"pk": 1})

    @as_auth
    def test_post(self):
        res = self.client.post(
            reverse("work_type_edit", kwargs={"pk": 1}),
            data={"title": "buzz"},
            follow=True,
        )
        self.assertContains(res, "updated")
        self.assertTrue(WorkType.objects.filter(title="buzz").exists())


class DeleteWorkTypeViewTest(CachelessTestCase):
    fixtures = ["test.json"]

    def test_render(self):
        privately_available(self, "work_type_delete", kwargs={"pk": 1})

    @as_auth
    def test_post(self):
        self.client.post(reverse("work_type_delete", kwargs={"pk": 1}), follow=True)
        self.assertFalse(WorkType.objects.filter(pk=1).exists())


class WorkTypeMergeViewTest(CachelessTestCase):
    fixtures = ["test.json"]

    def test_render(self):
        privately_available(self, "work_type_merge", kwargs={"work_type_id": 1})

    @as_auth
    def test_404(self):
        res = self.client.get(
            reverse("work_type_merge", kwargs={"work_type_id": 100}), follow=True
        )
        self.assertEqual(res.status_code, 404)

    @as_auth
    def test_post(self):
        res = self.client.post(
            reverse("work_type_merge", kwargs={"work_type_id": 1}),
            data={"into": 2},
            follow=True,
        )
        expected_redirect = reverse("work_type_edit", kwargs={"pk": 2})
        self.assertRedirects(res, expected_redirect)
        self.assertFalse(WorkType.objects.filter(pk=1).exists())
        self.assertContains(res, "updated")
        self.assertContains(res, "deleted")

    @as_auth
    def test_invalid_work_type(self):
        res = self.client.post(
            reverse("work_type_merge", kwargs={"work_type_id": 1}),
            data={"into": 1},
            follow=True,
        )
        expected_redirect = reverse("work_type_merge", kwargs={"work_type_id": 1})
        self.assertRedirects(res, expected_redirect)
        self.assertContains(res, "You cannot merge a work_type into itself")


class CreateWorkTest(CachelessTestCase):
    fixtures = ["test.json"]

    def test_render(self):
        privately_available(self, "work_create")

    @as_auth
    def test_post(self):
        res = self.client.post(
            reverse("work_create"),
            data={"title": "fizzbuzz", "work_type": 3},
            follow=True,
        )
        self.assertContains(res, "created")


class StaffAccessTest(CachelessTestCase):
    """Staff-gated routes redirect authenticated non-staff users home with a warning.

    LoginRequiredMiddleware handles anonymous users (redirect to login); the
    UserPassesTestMixin-based StaffRequiredMixin (CBVs) and @user_is_staff
    decorator (FBVs) handle the authenticated non-staff case.
    """

    fixtures = ["test.json"]

    def setUp(self):
        super().setUp()
        User = get_user_model()
        self.non_staff = User.objects.create_user(
            username="nonstaff", password="pw", is_staff=False
        )

    def test_non_staff_redirected_from_staff_cbv(self):
        # Exercises the StaffRequiredMixin -> UserPassesTestMixin CBV path
        # (ConferenceCreate, a StaffRequiredMixin CBV). A GET by a non-staff user
        # redirects via handle_no_permission before any form processing.
        self.client.force_login(self.non_staff)
        url = reverse("conference_create")
        res = self.client.get(url)
        self.assertEqual(res.status_code, 302)
        self.assertEqual(res["Location"], reverse("home_view"))
        from django.contrib.messages import get_messages

        self.assertIn(
            PERMISSIONS_ERROR_TEXT,
            [m.message for m in get_messages(res.wsgi_request)],
        )

    def test_non_staff_redirected_from_staff_fbv(self):
        # Exercises the @user_is_staff decorator path (author_merge_view FBV).
        self.client.force_login(self.non_staff)
        url = reverse("author_merge", kwargs={"author_id": 1})
        res = self.client.get(url)
        self.assertEqual(res.status_code, 302)
        self.assertEqual(res["Location"], reverse("home_view"))
        from django.contrib.messages import get_messages

        self.assertIn(
            PERMISSIONS_ERROR_TEXT,
            [m.message for m in get_messages(res.wsgi_request)],
        )

    def test_anonymous_redirected_to_login(self):
        # Sanity check that middleware still gates anonymous users. Use follow=True
        # so the redirect chain (302 -> APPEND_SLASH -> login page) resolves before
        # assertRedirects inspects it, matching the established privately_available
        # pattern (which would otherwise trip over the /accounts/login 301).
        url = reverse("conference_edit", kwargs={"pk": 1})
        res = self.client.get(url, follow=True)
        self.assertRedirects(res, f"{reverse('login')}?next={url}")

    def test_public_view_remains_anonymous(self):
        # A cache_for_anon public view stays accessible without login.
        self.assertEqual(self.client.get(reverse("home_view")).status_code, 200)

    def test_autocomplete_remains_anonymous(self):
        # Preserve the currently-anonymous autocomplete behavior.
        self.assertEqual(self.client.get(reverse("work-autocomplete")).status_code, 200)

    def test_public_downloads_remain_anonymous(self):
        # The two @login_not_required public downloads must NOT be login-gated by
        # the middleware. They serve FileResponse from a ZIP on disk that may be
        # absent in the test environment (same root cause as the pre-existing
        # DownloadPageTest.test_render failure), yielding HTTP 500, not 302.
        # Raising the client's raise_request_exception flag off lets us inspect
        # that 500 response instead of the client re-raising the FileNotFoundError.
        # The important assertion is that anonymous access is NOT redirected to
        # login (not 302).
        self.client.raise_request_exception = False
        res = self.client.get(reverse("works_download"))
        self.assertNotEqual(res.status_code, 302)
        res2 = self.client.get(reverse("public_all_tables_download"))
        self.assertNotEqual(res2.status_code, 302)
        self.client.raise_request_exception = True
