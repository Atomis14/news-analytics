# Extract article text and publisher metadata from Kontrast HTML.
import json
from html import unescape
from pathlib import Path

from bs4 import BeautifulSoup


# Parse publisher articles, returning None for other page types.
def parse_article(html: str) -> dict[str, object] | None:
    soup = BeautifulSoup(html, "html.parser")

    # Identify article pages from their JSON-LD before reading body markup.
    schema = json.loads(soup.select_one('script.yoast-schema-graph').string)
    graph = schema["@graph"]
    article_data = next((item for item in graph if item.get("@type") == "Article"), None)
    if article_data is None:
        return None

    heading = soup.select_one("h1.jeg_post_title")
    content = soup.select_one(".jeg_custom_content_wrapper .entry-content .content-inner")
    if heading is None or content is None:
        raise ValueError("Article headline or body was not found")

    # Collect text and links from the article body elements.
    paragraphs = []
    links = []
    for child in content.children:
        if child.name == "div" and "kontr-entity-placement" in child.get("class", []):
            continue
        if child.name in {"p", "h2", "h3", "blockquote"}:
            text = child.get_text(" ", strip=True)
            if text:
                paragraphs.append(text)
            for link in child.find_all("a", href=True):
                links.append({"text": link.get_text(" ", strip=True), "url": link["href"]})

    # Resolve article author references to their publisher profile records.
    people = {item["@id"]: item for item in graph if item.get("@type") == "Person"}

    # Treat one author reference and a list of references the same way.
    author_refs = article_data["author"]
    if isinstance(author_refs, dict):
        author_refs = [author_refs]
    authors = [
        {"name": people[author["@id"]]["name"], "profile_url": people[author["@id"]]["url"]}
        for author in author_refs
    ]

    # Keep publisher tags and categories as separate lists.
    tags = article_data.get("keywords", [])
    categories = [unescape(section) for section in article_data.get("articleSection", [])]

    return {
        "headline": heading.get_text(" ", strip=True),
        "body_text": "\n\n".join(paragraphs),
        "canonical_url": article_data["mainEntityOfPage"]["@id"],
        "published_at": article_data["datePublished"],
        "modified_at": article_data.get("dateModified"),
        "authors": authors,
        "tags": tags,
        "categories": categories,
        "links": links,
    }


# Read each saved HTML page and print its fields for manual inspection.
if __name__ == "__main__":
    debug_folder = Path(__file__).parent / "debug_articles"
    for sample in sorted(debug_folder.glob("*.html")):
        article = parse_article(sample.read_text(encoding="utf-8"))
        print("\n" + "=" * 80)
        print("FILE:", sample.name)
        if article is None:
            print("SKIPPED: No Article JSON-LD record")
            continue
        print("HEADLINE:", article["headline"])
        print("URL:", article["canonical_url"])
        print("PUBLISHED:", article["published_at"])
        print("MODIFIED:", article["modified_at"])
        for author in article["authors"]:
            print("AUTHOR:", author["name"], author["profile_url"])
        print("TAGS:", article["tags"])
        print("CATEGORIES:", article["categories"])
        print("LINKS:")
        for link in article["links"]:
            print(" -", link["text"], "=>", link["url"])
        # print("BODY:\n", article["body_text"])
