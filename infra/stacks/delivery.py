"""W3-0/W3-1: 結果配信基盤 + ジョブ API (設計: docs/design/web.md)。

- S3 バケット (非公開・全パブリックアクセスブロック)。結果 HTML を r/{id}.html に置く。
  r/anon/ と uploads/ は自動削除 (匿名30日・アップロード7日)
- CloudFront (OAC 経由でのみ S3 に到達、HTTPS 強制)。/api/* は HTTP API へ、
  / は入力 UI (web/index.html)。独自ドメインは後付け
- ジョブ実行 (W3-1): 同一コンテナイメージの Lambda 2関数 (api / worker)。
  api がジョブを DynamoDB に登録し worker を非同期起動、worker が compare →
  HTML を S3 へ書く。UI はポーリングで完成を待つ
- AWS Budgets: 月額の実績アラート (メールは -c alert_email= で指定。未指定なら作らない)
"""

from aws_cdk import (
    CfnOutput,
    Duration,
    RemovalPolicy,
    Size,
    Stack,
    aws_apigatewayv2 as apigwv2,
    aws_apigatewayv2_integrations as apigw_integrations,
    aws_budgets as budgets,
    aws_cloudfront as cloudfront,
    aws_cloudfront_origins as origins,
    aws_dynamodb as dynamodb,
    aws_lambda as lambda_,
    aws_s3 as s3,
    aws_s3_deployment as s3deploy,
)
from constructs import Construct

MONTHLY_BUDGET_USD = 20  # 想定コスト数百円に対する天井 (~3,000円)
MAX_UPLOAD_BYTES = 100 * 1024 * 1024  # zip アップロード上限 (web.md)


class DeliveryStack(Stack):
    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        bucket = s3.Bucket(
            self,
            "Results",
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            encryption=s3.BucketEncryption.S3_MANAGED,
            enforce_ssl=True,
            # 公開済みレポートは消さない (スタック削除時も保持)
            removal_policy=RemovalPolicy.RETAIN,
            lifecycle_rules=[
                s3.LifecycleRule(
                    id="expire-anonymous-results",
                    prefix="r/anon/",
                    expiration=Duration.days(30),
                ),
                s3.LifecycleRule(
                    id="expire-uploads",
                    prefix="uploads/",
                    expiration=Duration.days(7),
                ),
            ],
            # アップロード (presigned POST) はブラウザから S3 エンドポイントへ
            # 直接届くため CORS が必要
            cors=[
                s3.CorsRule(
                    allowed_methods=[s3.HttpMethods.POST, s3.HttpMethods.PUT],
                    allowed_origins=["*"],
                    allowed_headers=["*"],
                    max_age=3600,
                )
            ],
        )

        # --- ジョブ実行 (W3-1) ---

        jobs_table = dynamodb.Table(
            self,
            "Jobs",
            partition_key=dynamodb.Attribute(
                name="job_id", type=dynamodb.AttributeType.STRING
            ),
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
            time_to_live_attribute="expire_at",
            removal_policy=RemovalPolicy.DESTROY,  # ジョブ行は使い捨て
        )

        image_dir = "../"  # ビルドコンテキスト = リポジトリルート (.dockerignore 参照)
        common_env = {
            "RESULTS_BUCKET": bucket.bucket_name,
            "JOBS_TABLE": jobs_table.table_name,
            "MAX_UPLOAD_BYTES": str(MAX_UPLOAD_BYTES),
        }
        worker_fn = lambda_.DockerImageFunction(
            self,
            "Worker",
            code=lambda_.DockerImageCode.from_image_asset(
                image_dir,
                file="infra/runtime/Dockerfile",
                cmd=["handler.worker"],
            ),
            # Apple Silicon でのローカルビルド (arm64) と一致させる
            architecture=lambda_.Architecture.ARM_64,
            memory_size=2048,
            ephemeral_storage_size=Size.gibibytes(2),
            timeout=Duration.minutes(15),
            environment=common_env,
            description="gtfs-semantic-diff compare worker",
        )
        api_fn = lambda_.DockerImageFunction(
            self,
            "Api",
            code=lambda_.DockerImageCode.from_image_asset(
                image_dir,
                file="infra/runtime/Dockerfile",
                cmd=["handler.api"],
            ),
            architecture=lambda_.Architecture.ARM_64,
            memory_size=512,
            timeout=Duration.seconds(29),
            environment={**common_env, "WORKER_FUNCTION": ""},
            description="gtfs-semantic-diff job API",
        )
        # 循環参照を避けて後から設定
        api_fn.add_environment("WORKER_FUNCTION", worker_fn.function_name)

        bucket.grant_read_write(worker_fn)
        bucket.grant_put(api_fn, "uploads/*")  # presigned POST の署名元
        jobs_table.grant_read_write_data(worker_fn)
        jobs_table.grant_read_write_data(api_fn)
        worker_fn.grant_invoke(api_fn)

        http_api = apigwv2.HttpApi(
            self,
            "JobApi",
            default_integration=apigw_integrations.HttpLambdaIntegration(
                "ApiIntegration", api_fn
            ),
        )
        # 素朴なスロットリング (本格ガードは W3-2)
        stage = http_api.default_stage.node.default_child
        stage.default_route_settings = apigwv2.CfnStage.RouteSettingsProperty(
            throttling_rate_limit=10, throttling_burst_limit=20
        )

        distribution = cloudfront.Distribution(
            self,
            "Cdn",
            comment="gtfs-semantic-diff results",
            default_root_object="index.html",
            default_behavior=cloudfront.BehaviorOptions(
                origin=origins.S3BucketOrigin.with_origin_access_control(bucket),
                viewer_protocol_policy=cloudfront.ViewerProtocolPolicy.REDIRECT_TO_HTTPS,
                cache_policy=cloudfront.CachePolicy.CACHING_OPTIMIZED,
                compress=True,
            ),
            additional_behaviors={
                "/api/*": cloudfront.BehaviorOptions(
                    origin=origins.HttpOrigin(
                        f"{http_api.api_id}.execute-api.{self.region}.amazonaws.com"
                    ),
                    viewer_protocol_policy=cloudfront.ViewerProtocolPolicy.HTTPS_ONLY,
                    cache_policy=cloudfront.CachePolicy.CACHING_DISABLED,
                    origin_request_policy=cloudfront.OriginRequestPolicy.ALL_VIEWER_EXCEPT_HOST_HEADER,
                    allowed_methods=cloudfront.AllowedMethods.ALLOW_ALL,
                ),
            },
            # 日本を含むアジアのエッジまで (ALL より安い)
            price_class=cloudfront.PriceClass.PRICE_CLASS_200,
        )

        # 入力 UI (web/) をバケット直下へ配備。prune は絶対に無効
        # (有効だと r/ の公開済みレポートが消される)
        s3deploy.BucketDeployment(
            self,
            "WebUi",
            sources=[s3deploy.Source.asset("../web")],
            destination_bucket=bucket,
            prune=False,
            distribution=distribution,
            distribution_paths=["/index.html", "/"],
        )

        alert_email = self.node.try_get_context("alert_email")
        if alert_email:
            budgets.CfnBudget(
                self,
                "MonthlyBudget",
                budget=budgets.CfnBudget.BudgetDataProperty(
                    budget_name="gtfs-semantic-diff-monthly",
                    budget_type="COST",
                    time_unit="MONTHLY",
                    budget_limit=budgets.CfnBudget.SpendProperty(
                        amount=MONTHLY_BUDGET_USD, unit="USD"
                    ),
                ),
                notifications_with_subscribers=[
                    budgets.CfnBudget.NotificationWithSubscribersProperty(
                        notification=budgets.CfnBudget.NotificationProperty(
                            comparison_operator="GREATER_THAN",
                            notification_type="ACTUAL",
                            threshold=pct,
                            threshold_type="PERCENTAGE",
                        ),
                        subscribers=[
                            budgets.CfnBudget.SubscriberProperty(
                                address=alert_email, subscription_type="EMAIL"
                            )
                        ],
                    )
                    for pct in (50, 100)
                ],
            )

        CfnOutput(self, "BucketName", value=bucket.bucket_name)
        CfnOutput(self, "DistributionId", value=distribution.distribution_id)
        CfnOutput(self, "DistributionDomain", value=distribution.distribution_domain_name)
        CfnOutput(self, "ApiEndpoint", value=http_api.api_endpoint)
        CfnOutput(self, "JobsTable", value=jobs_table.table_name)
