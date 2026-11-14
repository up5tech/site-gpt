import unittest
from types import SimpleNamespace
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from site_gpt.app import models
from site_gpt.app.api import website as website_api
from site_gpt.app.db.base import Base

# Two different companies whose sitemaps list the same URLs (a shared theme,
# a shared docs domain, or simply the same site hosted for two tenants).
SHARED_URLS = [
    "https://shared.example.com/about",
    "https://shared.example.com/pricing",
]


class SiteMapSyncTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite+pysqlite:///:memory:")
        Base.metadata.create_all(
            self.engine,
            tables=[
                models.Company.__table__,
                models.Website.__table__,
                models.WebsitePage.__table__,
            ],
        )
        self.db = sessionmaker(bind=self.engine)()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def make_website(self, company_name):
        company = models.Company(name=company_name, description="")
        self.db.add(company)
        self.db.commit()
        self.db.refresh(company)

        site = models.Website(
            url="https://shared.example.com",
            name=company_name,
            site_map_url="https://shared.example.com/sitemap.xml",
            company_id=company.id,
        )
        self.db.add(site)
        self.db.commit()
        self.db.refresh(site)
        return company, site

    def sync(self, site, company):
        user = SimpleNamespace(company_id=company.id)
        with patch.object(
            website_api, "extract_urls_from_sitemap", return_value=list(SHARED_URLS)
        ):
            website_api.load_website_site_map(site.id, self.db, user)

    def pages_of(self, site):
        return sorted(
            page.url
            for page in self.db.query(models.WebsitePage)
            .filter(models.WebsitePage.website_id == site.id)
            .all()
        )

    def test_each_website_gets_its_own_pages_for_shared_urls(self):
        company_a, site_a = self.make_website("Company A")
        company_b, site_b = self.make_website("Company B")

        self.sync(site_a, company_a)
        self.assertEqual(self.pages_of(site_a), sorted(SHARED_URLS))

        # Regression: this used to add nothing, because the dedupe matched
        # Company A's rows by URL alone and skipped them.
        self.sync(site_b, company_b)
        self.assertEqual(self.pages_of(site_b), sorted(SHARED_URLS))
        self.assertEqual(self.db.query(models.WebsitePage).count(), 4)

    def test_syncing_twice_does_not_duplicate_pages(self):
        company, site = self.make_website("Company A")

        self.sync(site, company)
        self.sync(site, company)

        self.assertEqual(self.pages_of(site), sorted(SHARED_URLS))
        self.assertEqual(self.db.query(models.WebsitePage).count(), len(SHARED_URLS))


if __name__ == "__main__":
    unittest.main()
