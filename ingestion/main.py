# Save a bounded number of unsaved articles from matching post sitemaps.
import re
import urllib.error
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
    max_articles = event.get("max_articles", 1)

    # Check each article and save up to the requested number of new ones.
    table = boto3.resource("dynamodb", region_name="eu-north-1").Table(TABLE)
    saved_urls = []
    failed_urls = []
    for sitemap_url in selected_sitemaps:
        print(f"Checking sitemap: {sitemap_url}")
        for article in read_xml(sitemap_url).findall("{*}url"):
            article_url = article.findtext("{*}loc").strip()
            article_key = article_url.rstrip("/")
            if table.get_item(Key={"article_url": article_key}, ConsistentRead=True).get("Item"):
                continue

            # Fetch the new article and save its original HTML bytes to S3.
            print(f"Selected article: {article_url}")
            request = urllib.request.Request(article_url, headers={"User-Agent": "news-analytics-scraper/0.1"})
            try:
                with urllib.request.urlopen(request, timeout=20) as response:
                    html = response.read()
                    content_type = response.headers.get("Content-Type", "text/html")
            except urllib.error.URLError as error:
                print(f"Download failed: {article_url}: {error}")
                failed_urls.append(article_url)
                continue

            parsed_url = urlparse(article_url)
            s3_key = f"{parsed_url.hostname}{parsed_url.path.rstrip('/')}.html"
            boto3.client("s3").put_object(Bucket=BUCKET, Key=s3_key, Body=html, ContentType=content_type)
            print(f"Uploaded to S3: s3://{BUCKET}/{s3_key}")

            # Record success after S3 confirms the upload.
            item = {
                "article_url": article_key,
                "original_url": article_url,
                "publisher_domain": parsed_url.hostname,
                "first_downloaded_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
                "sitemap_lastmod": article.findtext("{*}lastmod"),
                "s3_key": s3_key,
            }
            table.put_item(Item=item, ConditionExpression="attribute_not_exists(article_url)")
            print(f"Recorded in DynamoDB: {article_key}")
            saved_urls.append(article_url)
            if len(saved_urls) >= max_articles:
                break
        if len(saved_urls) >= max_articles:
            break

    # Return both successful and failed article URLs from this invocation.
    return {"statusCode": 200, "saved_count": len(saved_urls), "saved_urls": saved_urls, "failed_urls": failed_urls}
