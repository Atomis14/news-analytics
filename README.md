# News Analytics Pipeline with AWS and Databricks

## Current scraper

`ingestion/main.py` is the source for the `news-analytics-scraper` AWS Lambda function. It reads `https://kontrast.at/sitemap_index.xml` and follows only `post-sitemap.xml` and numbered variants such as `post-sitemap2.xml`. It checks article URLs in sitemap order and saves a bounded number of articles that are absent from DynamoDB.

`ingestion/debug.ipynb` contains the local, step-by-step checks for sitemap discovery, article URLs and `lastmod`, and a raw HTML download.

## AWS resources

| Resource | Value |
| --- | --- |
| Lambda function | `news-analytics-scraper` |
| Lambda handler | `main.lambda_handler` |
| Lambda timeout used in tests | 45 seconds |
| S3 bucket | `databricks-news-articles` |
| DynamoDB table | `news-analytics-articles` in `eu-north-1` |
| DynamoDB partition key | `article_url` (String); no sort key |
| CloudWatch log group | `/aws/lambda/news-analytics-scraper` |

The Lambda execution role needs `s3:PutObject` for objects in the bucket, `dynamodb:GetItem` and `dynamodb:PutItem` for the table, and CloudWatch Logs write permissions. These permissions have been exercised by successful Console tests.

## Deploy and test in the AWS Console

1. Open the Lambda function's **Code** tab. Copy the contents of `ingestion/main.py` into a top-level file named `main.py`, then choose **Deploy**.
2. Check **Runtime settings**: the handler must be `main.lambda_handler`. Check **Configuration → General configuration**: the tested timeout is 30 seconds.
3. On the **Test** tab, run `{}` to save at most one new article. Run `{"max_articles":2}` to save at most two. To limit the run to the second matching post sitemap, use `{"post_sitemap_index":1,"max_articles":2}`. Sitemap positions are zero-based.
4. Inspect the test response and Function Logs. The current local code returns `statusCode`, `saved_count`, `saved_urls`, and `failed_urls`. Confirm new S3 objects in the bucket and new items under **DynamoDB → Explore table items**.

The local file is the source of truth after temporary Console experiments. Restore it to Lambda and deploy again when a test required a temporary code change.

## Storage and retry behavior

For each sitemap article, the scraper removes the URL's trailing slash for the DynamoDB `article_url` key. It keeps the sitemap URL in `original_url`. For example, the article at `https://kontrast.at/wie-studieren-schlau-und-nicht-arm-macht/` uses the key `https://kontrast.at/wie-studieren-schlau-und-nicht-arm-macht` and S3 object key `kontrast.at/wie-studieren-schlau-und-nicht-arm-macht.html`.

The scraper checks DynamoDB before downloading. For a new article, it uploads the original HTML bytes to S3, then writes the DynamoDB item with `article_url`, `original_url`, `publisher_domain`, `first_downloaded_at` (UTC), `sitemap_lastmod`, and `s3_key`. The conditional write preserves an existing item. Article download errors appear in `failed_urls`; those URLs receive no S3 upload or DynamoDB item and can be retried on another run. S3 and DynamoDB errors stop the invocation.

Each invocation starts at the beginning of the selected sitemaps, so DynamoDB lookup work grows as more URLs are saved. A batch of two articles was tested successfully in about 12.5 seconds with the 30-second Lambda timeout. If S3 succeeds but the DynamoDB write fails, a later run can upload again to the same S3 key.

CloudFormation, scheduling, and Databricks integration are later steps.
