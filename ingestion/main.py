# Download one Kontrast article and save its original HTML bytes to S3.
import urllib.request

import boto3


BUCKET = "databricks-news-articles"
ARTICLE_URL = "https://kontrast.at/wie-studieren-schlau-und-nicht-arm-macht/"
S3_KEY = "kontrast.at/wie-studieren-schlau-und-nicht-arm-macht.html"


def lambda_handler(event, context):
    request = urllib.request.Request(ARTICLE_URL, headers={"User-Agent": "news-analytics-scraper/0.1"})
    with urllib.request.urlopen(request, timeout=20) as response:
        html = response.read()
        content_type = response.headers.get("Content-Type", "text/html")

    boto3.client("s3").put_object(Bucket=BUCKET, Key=S3_KEY, Body=html, ContentType=content_type)
    return {"statusCode": 200, "body": f"Saved {len(html)} bytes to s3://{BUCKET}/{S3_KEY}"}
