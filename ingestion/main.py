# Save a bounded number of unsaved articles from matching post sitemaps.
import re
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
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


# Check whether a sitemap timestamp falls outside the requested age window.
def is_older_than(lastmod, cutoff):
    if cutoff is None or not lastmod:
        return False
    modified_at = datetime.fromisoformat(lastmod.replace("Z", "+00:00"))
    if modified_at.tzinfo is None:
        modified_at = modified_at.replace(tzinfo=timezone.utc)
    return modified_at < cutoff


def lambda_handler(event, context):
    # Find post sitemaps and apply an optional zero-based test selection.
    max_age_days = event.get("max_age_days")
    cutoff = datetime.now(timezone.utc) - timedelta(days=max_age_days) if max_age_days is not None else None
    index = read_xml(SITEMAP_INDEX)
    post_sitemaps = []
    for sitemap in index.findall(".//{*}sitemap"):
        sitemap_url = sitemap.findtext("{*}loc").strip()
        filename = urlparse(sitemap_url).path.rsplit("/", 1)[-1]
        if re.fullmatch(r"post-sitemap(?:\d+)?\.xml", filename):
            post_sitemaps.append((sitemap_url, sitemap.findtext("{*}lastmod")))

    post_sitemap_index = event.get("post_sitemap_index")
    selected_sitemaps = post_sitemaps if post_sitemap_index is None else [post_sitemaps[post_sitemap_index]]
    max_articles = event.get("max_articles", 1)

    # Check each article and save up to the requested number of new ones.
    table = boto3.resource("dynamodb", region_name="eu-north-1").Table(TABLE)
    saved_urls = []
    failed_urls = []
    stopped_early = False
    for sitemap_url, sitemap_lastmod in selected_sitemaps:
        # Skip old sitemap files before making another HTTP request.
        if is_older_than(sitemap_lastmod, cutoff):
            print(f"Skipping old sitemap: {sitemap_url}")
            continue
        # Leave time to finish the current invocation before Lambda's timeout.
        if context.get_remaining_time_in_millis() < 45_000:
            stopped_early = True
            print(f"Stopping with {context.get_remaining_time_in_millis()} ms remaining")
            break
        print(f"Checking sitemap: {sitemap_url}")
        for article in read_xml(sitemap_url).findall("{*}url"):
            # Stop before starting another article when little time remains.
            if context.get_remaining_time_in_millis() < 45_000:
                stopped_early = True
                print(f"Stopping with {context.get_remaining_time_in_millis()} ms remaining")
                break
            # Keep entries without lastmod; skip older entries before looking them up in DynamoDB.
            lastmod = article.findtext("{*}lastmod")
            if is_older_than(lastmod, cutoff):
                continue

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
                "sitemap_lastmod": lastmod,
                "s3_key": s3_key,
            }
            table.put_item(Item=item, ConditionExpression="attribute_not_exists(article_url)")
            print(f"Recorded in DynamoDB: {article_key}")
            saved_urls.append(article_url)
            if len(saved_urls) >= max_articles:
                break
        if stopped_early or len(saved_urls) >= max_articles:
            break

    # Return both successful and failed article URLs from this invocation.
    return {
        "statusCode": 200,
        "saved_count": len(saved_urls),
        "saved_urls": saved_urls,
        "failed_urls": failed_urls,
        "stopped_early": stopped_early,
    }
