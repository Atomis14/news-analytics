# Extract article text and publisher metadata from Kontrast HTML.
import json
from pathlib import Path

from bs4 import BeautifulSoup


# Parse the visible article elements and the publisher's JSON-LD metadata.
def parse_article(html: str) -> dict[str, object]:
    soup = BeautifulSoup(html, "html.parser")
    heading = soup.select_one("h1.jeg_post_title")
    content = soup.select_one(".jeg_custom_content_wrapper .entry-content .content-inner")
    if heading is None or content is None:
        raise ValueError("Article headline or body was not found")

    # Make raw text from the article body.
    paragraphs = []
    for child in content.children:
        if child.name == "div" and "kontr-entity-placement" in child.get("class", []):
            continue
        if child.name in {"p", "h2", "h3", "blockquote"}:
            text = child.get_text(" ", strip=True)
            if text:
                paragraphs.append(text)

    # Resolve article author references to their publisher profile records.
    schema = json.loads(soup.select_one('script.yoast-schema-graph').string)
    graph = schema["@graph"]
    article_data = next(item for item in graph if item.get("@type") == "Article")
    people = {item["@id"]: item for item in graph if item.get("@type") == "Person"}
    authors = [
        {"name": people[author["@id"]]["name"], "profile_url": people[author["@id"]]["url"]}
        for author in article_data["author"]
    ]

    return {
        "headline": heading.get_text(" ", strip=True),
        "body_text": "\n\n".join(paragraphs),
        "canonical_url": article_data["mainEntityOfPage"]["@id"],
        "published_at": article_data["datePublished"],
        "modified_at": article_data["dateModified"],
        "authors": authors,
    }


# Read each saved HTML page and print its fields for manual inspection.
if __name__ == "__main__":
    debug_folder = Path(__file__).parent / "debug_articles"
    for sample in sorted(debug_folder.glob("*.html")):
        article = parse_article(sample.read_text(encoding="utf-8"))
        print("\n" + "=" * 80)
        print("FILE:", sample.name)
        print("HEADLINE:", article["headline"])
        print("URL:", article["canonical_url"])
        print("PUBLISHED:", article["published_at"])
        print("MODIFIED:", article["modified_at"])
        for author in article["authors"]:
            print("AUTHOR:", author["name"], author["profile_url"])
        # print("BODY:\n", article["body_text"])
