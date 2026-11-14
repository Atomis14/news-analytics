# Read a selected post sitemap article, then save it only if DynamoDB has no record.
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
    # Select one article by its zero-based position in the first post sitemap.
    index = read_xml(SITEMAP_INDEX)
    post_sitemaps = []
    for loc in index.findall(".//{*}sitemap/{*}loc"):
        filename = urlparse(loc.text).path.rsplit("/", 1)[-1]
        if re.fullmatch(r"post-sitemap(?:\d+)?\.xml", filename):
            post_sitemaps.append(loc.text.strip())

    article_index = event.get("article_index", 0)
    article = read_xml(post_sitemaps[0]).findall("{*}url")[article_index]
    article_url = article.findtext("{*}loc").strip()
    sitemap_lastmod = article.findtext("{*}lastmod")
    article_key = article_url.rstrip("/")
    parsed_url = urlparse(article_url)
    s3_key = f"{parsed_url.hostname}{parsed_url.path.rstrip('/')}.html"

    # Check the full article URL before making another download.
    table = boto3.resource("dynamodb", region_name="eu-north-1").Table(TABLE)
    if table.get_item(Key={"article_url": article_key}, ConsistentRead=True).get("Item"):
        return {"statusCode": 200, "body": f"Skipped previously saved article: {article_key}"}

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
