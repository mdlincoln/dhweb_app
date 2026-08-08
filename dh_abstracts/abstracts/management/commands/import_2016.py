from django.core.management.base import BaseCommand
from django.conf import settings
from abstracts import models
import json
from django.db import transaction
from django.contrib.postgres.search import SearchRank, SearchQuery
from django.db.models import F


class Command(BaseCommand):
    help = "One-time load of DH 2016 full text"

    def add_arguments(self, parser):
        pass

    @transaction.atomic
    def handle(self, *args, **options):
        # all_xmls = glob("{base}/xml/*.xml")
        # output_list = []
        # for x in all_xmls:
        #     root = etree.parse(x)
        #     title_node = root.find("//{http://www.tei-c.org/ns/1.0}title")
        #     title = "".join(title_node.itertext()).strip()
        #     if title == "":
        #         print(x)
        #         raise
        #     full_text = etree.tostring(
        #         root.find("//{http://www.tei-c.org/ns/1.0}text")
        #     ).decode("utf-8")
        #     output_list.append({"title": title, "full_text": full_text})
        # json.dump(output_list, open("{base}/ft2016.json", "w"))

        all_texts = json.load(
            open(f"{settings.DATA_OUTPUT_PATH}/ft2016.json", "r")
        )
        adho2016 = models.Conference.objects.get(id=17)
        for t in all_texts:
            # find closest match:
            title = t["title"]
            target_work = (
                models.Work.objects.filter(conference=adho2016, search_text=title)
                .annotate(rank=SearchRank(F("search_text"), SearchQuery(title)))
                .filter(rank__gte=0)
                .order_by("-rank")
            ).first()
            if target_work is not None:
                target_work.full_text = t["full_text"]
                target_work.full_text_type = "xml"
                target_work.save()
            else:
                print(title)
