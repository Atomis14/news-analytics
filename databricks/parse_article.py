# Extract the headline and article text from one Kontrast HTML page.
from pathlib import Path

from bs4 import BeautifulSoup


# Parse the visible article elements while stopping before the embedded poll.
def parse_article(html: str) -> dict[str, str]:
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

    return {
        "headline": heading.get_text(" ", strip=True),
        "body_text": "\n\n".join(paragraphs),
    }


# Read each saved HTML page and print its fields for manual inspection.
if __name__ == "__main__":
    debug_folder = Path(__file__).parent / "debug_articles"
    for sample in sorted(debug_folder.glob("*.html")):
        article = parse_article(sample.read_text(encoding="utf-8"))
        print("\n" + "=" * 80)
        print("FILE:", sample.name)
        print("HEADLINE:", article["headline"])
        print("BODY:\n", article["body_text"])
