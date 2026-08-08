from django.test import TestCase
from django.core.files.storage import default_storage, storages


class StorageConfigTest(TestCase):
    """Smoke test: STORAGES setting resolves to expected backends."""

    def test_default_storage_is_filesystem(self):
        from django.core.files.storage import FileSystemStorage

        self.assertIsInstance(default_storage, FileSystemStorage)

    def test_staticfiles_storage_resolves(self):
        from django.contrib.staticfiles.storage import StaticFilesStorage

        self.assertIsInstance(storages["staticfiles"], StaticFilesStorage)

    def test_easy_thumbnails_alias_resolves(self):
        # AC.2: The easy_thumbnails alias must resolve without InvalidStorageError.
        from easy_thumbnails.storage import ThumbnailFileSystemStorage

        self.assertIsInstance(storages["easy_thumbnails"], ThumbnailFileSystemStorage)

    def test_filer_public_storage_unaffected(self):
        # AC.3: filer storage must still resolve to PublicFileSystemStorage
        # with the expected location.
        from filer.settings import FILER_PUBLICMEDIA_STORAGE
        from filer.storage import PublicFileSystemStorage

        self.assertIsInstance(FILER_PUBLICMEDIA_STORAGE, PublicFileSystemStorage)
        self.assertEqual(FILER_PUBLICMEDIA_STORAGE.location, "/vol/static_files/media")
