from django.test import TestCase
from django.db import connection, connections, models
from django.contrib.postgres.search import SearchQuery

from abstracts.models import (
    Conference,
    Work,
    Institution,
    Appellation,
    Language,
    Affiliation,
)
from lxml.etree import XMLSyntaxError, DocumentInvalid


class ConferenceXMLImportTest(TestCase):
    fixtures = ["test.json"]

    def test_load_file(self):
        conference = Conference.objects.first()

        conference.import_xml_file("abstracts/static/tei/valid_tei/abstract_tei.xml")
        self.assertTrue(
            Work.objects.filter(title__icontains="Archivos digitales").exists()
        )
        created_work = Work.objects.filter(
            title__icontains="Archivos digitales"
        ).first()
        self.assertEqual(created_work.conference, conference)
        self.assertIn(Language.objects.get(code="es"), created_work.languages.all())
        self.assertTrue(Appellation.objects.filter(first_name="Maria Jose").exists())
        self.assertEqual(created_work.authorships.count(), 2)
        self.assertTrue(
            Institution.objects.filter(name="Universidad de los Andes").exists()
        )
        self.assertTrue(
            Institution.objects.filter(name="Fundación Histórica Neogranadina").exists()
        )
        self.assertTrue(Institution.objects.filter(name="Harvard University").exists())
        self.assertTrue(
            Affiliation.objects.filter(department="Departamento de Historia").exists()
        )
        self.assertTrue(
            Affiliation.objects.filter(
                department="Berkman Klein Center for Internet and Society"
            ).exists()
        )

    def test_bad_file(self):
        conference = Conference.objects.first()
        self.assertRaises(
            XMLSyntaxError,
            conference.import_xml_file,
            filepath="abstracts/static/tei/invalid_tei/bad_tei.xml",
        )

    def test_invalid_tei(self):
        conference = Conference.objects.first()
        self.assertRaises(
            DocumentInvalid,
            conference.import_xml_file,
            filepath="abstracts/static/tei/invalid_tei/abstract_tei2.xml",
        )


class ConferenceXMLDirectoryImportTest(TestCase):
    fixtures = ["test.json"]

    def test_load_directory(self):
        conference = Conference.objects.first()

        import_response = conference.import_xml_directory(
            "abstracts/static/tei/valid_tei"
        )
        self.assertTrue(
            Work.objects.filter(title__icontains="Archivos digitales").exists()
        )
        self.assertTrue(
            Work.objects.filter(
                title__icontains="The Index of Digital Humanities Conferences"
            ).exists()
        )
        self.assertGreater(len(import_response["successful_files"]), 0)
        self.assertEqual(len(import_response["failed_files"]), 0)

    def test_load_bad_directory(self):
        conference = Conference.objects.first()

        import_response = conference.import_xml_directory(
            "abstracts/static/tei/invalid_tei"
        )
        self.assertFalse(
            Work.objects.filter(title__icontains="Archivos digitales").exists()
        )
        self.assertFalse(
            Work.objects.filter(
                title__icontains="The Index of Digital Humanities Conferences"
            ).exists()
        )
        self.assertGreater(len(import_response["failed_files"]), 0)
        self.assertGreater(len(import_response["successful_files"]), 0)


class PostgresModernizationTest(TestCase):
    """Verifies the PostgreSQL 18 + generated-FTS / BigAutoField / db_default modernization."""

    fixtures = ["test.json"]

    def test_pg_version(self):
        self.assertGreaterEqual(connections["default"].pg_version, 180000)

    def test_psycopg3_driver(self):
        driver_module = type(connection.connection).__module__
        self.assertTrue(
            driver_module.startswith("psycopg"),
            f"unexpected DB driver module: {driver_module}",
        )
        self.assertFalse(driver_module.startswith("psycopg2"), "psycopg2 still in use")

    def test_work_pk_is_bigauto(self):
        self.assertIsInstance(Work._meta.pk, models.BigAutoField)

    def test_bigint_pk_increments(self):
        conf = Conference.objects.first()
        first = Work.objects.create(conference=conf, title="First incremental work")
        second = Work.objects.create(conference=conf, title="Second incremental work")
        self.assertLess(first.pk, second.pk)

    def test_work_search_text_generated_column(self):
        conf = Conference.objects.first()
        work = Work.objects.create(
            conference=conf,
            title="Distinctive Search Tokens Plotkin",
            full_text="Some selected full text",
        )
        # The vector is derived by the database, not a save() hook.
        work.refresh_from_db()
        self.assertTrue(work.search_text)

    def test_work_search_text_db_derived_update(self):
        conf = Conference.objects.first()
        work = Work.objects.create(conference=conf, title="Original Title Tokens")
        # Bulk update() bypasses Work.save(); the generated column must still refresh.
        Work.objects.filter(pk=work.pk).update(
            title="Totally Distinct Supposedly Working Tokens"
        )
        work.refresh_from_db()
        self.assertTrue(work.search_text)
        self.assertTrue(
            Work.objects.filter(
                pk=work.pk, search_text=SearchQuery("Distinct")
            ).exists()
        )

    def test_search_text_is_generated_in_db(self):
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT a.attgenerated, pg_get_expr(d.adbin, d.adrelid)
                FROM pg_attribute a
                JOIN pg_attrdef d ON d.adrelid = a.attrelid AND d.adnum = a.attnum
                WHERE a.attrelid = 'abstracts_work'::regclass
                  AND a.attname = 'search_text'
                """
            )
            row = cursor.fetchone()
        # attgenerated: 's' = STORED generated column.
        self.assertEqual(row[0], "s")
        # Fixed immutable FTS config must be present in the expression.
        self.assertIn("'english'", row[1].lower())

    def test_db_default_empty_string(self):
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO abstracts_institution (name, last_updated)
                VALUES ('Raw Insert Institution', NOW())
                RETURNING id
                """
            )
            new_id = cursor.fetchone()[0]
        inst = Institution.objects.get(pk=new_id)
        self.assertEqual(inst.city, "")
