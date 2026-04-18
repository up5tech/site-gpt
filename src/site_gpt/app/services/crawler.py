from langchain_community.document_loaders import SitemapLoader


def load_sitemap(url: str):
    loader = SitemapLoader(web_path=url)
    return loader.load()
