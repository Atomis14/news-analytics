# News Analytics Pipeline with AWS and Databricks

## Current scraper

`ingestion/main.py` is the source for the `news-analytics-scraper` AWS Lambda function. It reads `https://kontrast.at/sitemap_index.xml` and follows only `post-sitemap.xml` and numbered variants such as `post-sitemap2.xml`. It checks article URLs in sitemap order and saves those that are absent from DynamoDB. It stops before the Lambda timeout or when an optional article limit is reached.

`ingestion/debug.ipynb` contains the local, step-by-step checks for sitemap discovery, article URLs and `lastmod`, and a raw HTML download.

## AWS resources

| Resource | Value |
| --- | --- |
| Lambda function | `news-analytics-scraper` |
| Lambda handler | `main.lambda_handler` |
| Lambda timeout | 3 minutes |
| S3 bucket | `databricks-news-articles` |
| DynamoDB table | `news-analytics-articles` in `eu-north-1` |
| DynamoDB partition key | `article_url` (String); no sort key |
| CloudWatch log group | `/aws/lambda/news-analytics-scraper` |

The Lambda execution role needs `s3:PutObject` for objects in the bucket, `dynamodb:BatchGetItem` and `dynamodb:PutItem` for the table, and CloudWatch Logs write permissions. These permissions have been exercised by successful Console tests.

## Lambda event parameters

All event parameters are optional. An empty event `{}` performs a full historic scan of all matching post sitemaps, saving unsaved articles until it reaches the end or stops with less than 45 seconds of Lambda time remaining.

| Parameter | Example | When omitted |
| --- | --- | --- |
| `max_age_days` | `7` | No age filter: check all post sitemaps and their articles. |
| `max_articles` | `10` | No article-count limit; the remaining-time check still applies. |
| `post_sitemap_index` | `1` | Check all matching post sitemaps. |

`max_age_days` is a number of days back from the current UTC time. The scraper applies it to each post sitemap's `lastmod` in the index and each article's `lastmod` within a selected sitemap. Missing `lastmod` values are checked rather than skipped. `max_articles` is a limit on **successful new saves**, not on URLs examined. `post_sitemap_index` is zero-based in the full list of matching post sitemaps; it selects only that sitemap, even if the age filter then skips it. The older `article_index` parameter is no longer used.

For a small manual backfill run, use `{"max_articles":10}`. For the future daily schedule, use `{"max_age_days":7}`. Do not use `{}` for the daily schedule: it scans the full historic list on every run.

## Deploy and test in the AWS Console

1. Open the Lambda function's **Code** tab. Copy the contents of `ingestion/main.py` into a top-level file named `main.py`, then choose **Deploy**.
2. Check **Runtime settings**: the handler must be `main.lambda_handler`. Check **Configuration → General configuration**: the timeout is 3 minutes.
3. On the **Test** tab, use `{"max_articles":1}` for one historic article or `{"max_age_days":7}` for an uncapped recent scan. To limit the run to the second matching post sitemap, use `{"post_sitemap_index":1,"max_articles":2}`.
4. Inspect the test response and Function Logs. The response contains `saved_count`, `saved_urls`, `failed_urls`, `stopped_early`, and `scan_finished`. The logs include a compact JSON summary with all of these except `saved_urls`. Confirm new S3 objects in the bucket and new items under **DynamoDB → Explore table items**.

The local file is the source of truth after temporary Console experiments. Restore it to Lambda and deploy again when a test required a temporary code change.

## Storage and retry behavior

For each sitemap article, the scraper removes the URL's trailing slash for the DynamoDB `article_url` key. It keeps the sitemap URL in `original_url`. For example, the article at `https://kontrast.at/wie-studieren-schlau-und-nicht-arm-macht/` uses the key `https://kontrast.at/wie-studieren-schlau-und-nicht-arm-macht` and S3 object key `kontrast.at/wie-studieren-schlau-und-nicht-arm-macht.html`.

The scraper checks DynamoDB in batches of up to 100 article URL keys before downloading. It retries DynamoDB `UnprocessedKeys` up to five attempts with increasing waits and stops with an error if any remain unresolved. For a new article, it uploads the original HTML bytes to S3, then writes the DynamoDB item with `article_url`, `original_url`, `publisher_domain`, `first_downloaded_at` (UTC), `sitemap_lastmod`, and `s3_key`. The conditional write preserves an existing item. Article download errors appear in `failed_urls`; those URLs receive no S3 upload or DynamoDB item and can be retried on another run. S3 and DynamoDB errors stop the invocation.

Each invocation starts at the beginning of the selected sitemaps. Batch lookups keep this practical for the one-time historic backfill; the age filter avoids checking old article entries during daily runs. `stopped_early: true` means the Lambda stopped before its timeout. `scan_finished: true` means it reached the end of the selected sitemaps; inspect `failed_urls` separately because a finished scan can still have failed downloads. If S3 succeeds but the DynamoDB write fails, a later run can upload again to the same S3 key.

The temporary historic backfill schedule and daily schedule have not been configured yet. CloudFormation and Databricks integration are later steps.
