# Skip saved articles, then download one article and track its successful S3 upload.
import re
import urllib.request
from datetime import datetime, timezone

import boto3


BUCKET = "databricks-news-articles"
TABLE = "news-analytics-articles"
ARTICLE_URL = "https://kontrast.at/wie-studieren-schlau-und-nicht-arm-macht/"
ARTICLE_KEY = ARTICLE_URL.rstrip("/")
SITEMAP_LASTMOD = "2017-04-12T21:00:53+00:00"
S3_KEY = "kontrast.at/wie-studieren-schlau-und-nicht-arm-macht.html"


def lambda_handler(event, context):
    # Check the full article URL before making another download.
    table = boto3.resource("dynamodb", region_name="eu-north-1").Table(TABLE)
    if table.get_item(Key={"article_url": ARTICLE_KEY}, ConsistentRead=True).get("Item"):
        return {"statusCode": 200, "body": f"Skipped previously saved article: {ARTICLE_KEY}"}

    # Fetch the HTML and save its original bytes to S3.
    request = urllib.request.Request(ARTICLE_URL, headers={"User-Agent": "news-analytics-scraper/0.1"})
    with urllib.request.urlopen(request, timeout=20) as response:
        html = response.read()
        content_type = response.headers.get("Content-Type", "text/html")

    boto3.client("s3").put_object(Bucket=BUCKET, Key=S3_KEY, Body=html, ContentType=content_type)

    # Record success after S3 confirms the upload.
    item = {
        "article_url": ARTICLE_KEY,
        "original_url": ARTICLE_URL,
        "publisher_domain": "kontrast.at",
        "first_downloaded_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "sitemap_lastmod": SITEMAP_LASTMOD,
        "s3_key": S3_KEY,
    }
    article_id = re.search(rb"\bpostid-(\d+)\b", html)
    if article_id:
        item["publisher_article_id"] = article_id.group(1).decode("ascii")
    table.put_item(Item=item, ConditionExpression="attribute_not_exists(article_url)")
    return {"statusCode": 200, "body": f"Saved {len(html)} bytes to s3://{BUCKET}/{S3_KEY}"}
