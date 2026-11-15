# Save the first unsaved article across post sitemaps or one selected sitemap.
import re
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from urllib.parse import urlparse

import boto3


BUCKET = "databricks-news-articles"
TABLE = "news-analytics-articles"
SITEMAP_INDEX = "https://kontrast.at/sitemap_index.xml"


# Fetch an XML sitemap using the same request headers as the article download.
def read_xml(url):
    request = urllib.request.Request(url, headers={"User-Agent": "news-analytics-scraper/0.1"})
    with urllib.request.urlopen(request, timeout=20) as response:
        return ET.fromstring(response.read())


def lambda_handler(event, context):
    # Find post sitemaps and apply an optional zero-based test selection.
    index = read_xml(SITEMAP_INDEX)
    post_sitemaps = []
    for loc in index.findall(".//{*}sitemap/{*}loc"):
        filename = urlparse(loc.text).path.rsplit("/", 1)[-1]
        if re.fullmatch(r"post-sitemap(?:\d+)?\.xml", filename):
            post_sitemaps.append(loc.text.strip())

    post_sitemap_index = event.get("post_sitemap_index")
    selected_sitemaps = post_sitemaps if post_sitemap_index is None else [post_sitemaps[post_sitemap_index]]

    # Find the first article without a DynamoDB record across the selected sitemaps.
    table = boto3.resource("dynamodb", region_name="eu-north-1").Table(TABLE)
    article = None
    for sitemap_url in selected_sitemaps:
        for candidate in read_xml(sitemap_url).findall("{*}url"):
            article_url = candidate.findtext("{*}loc").strip()
            article_key = article_url.rstrip("/")
            if not table.get_item(Key={"article_url": article_key}, ConsistentRead=True).get("Item"):
                article = candidate
                break
        if article is not None:
            break
    if article is None:
        return {"statusCode": 200, "body": "No new articles in the checked post sitemaps"}

    sitemap_lastmod = article.findtext("{*}lastmod")
    parsed_url = urlparse(article_url)
    s3_key = f"{parsed_url.hostname}{parsed_url.path.rstrip('/')}.html"

    # Fetch the HTML and save its original bytes to S3.
    request = urllib.request.Request(article_url, headers={"User-Agent": "news-analytics-scraper/0.1"})
    with urllib.request.urlopen(request, timeout=20) as response:
        html = response.read()
        content_type = response.headers.get("Content-Type", "text/html")

    boto3.client("s3").put_object(Bucket=BUCKET, Key=s3_key, Body=html, ContentType=content_type)

    # Record success after S3 confirms the upload.
    item = {
        "article_url": article_key,
        "original_url": article_url,
        "publisher_domain": parsed_url.hostname,
        "first_downloaded_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "sitemap_lastmod": sitemap_lastmod,
        "s3_key": s3_key,
    }
    table.put_item(Item=item, ConditionExpression="attribute_not_exists(article_url)")
    return {"statusCode": 200, "body": f"Saved {len(html)} bytes to s3://{BUCKET}/{s3_key}"}
