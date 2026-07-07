"""W3-0: 結果配信基盤 (設計: docs/design/web.md)。

- S3 バケット (非公開・全パブリックアクセスブロック)。結果 HTML を r/{id}.html に置く。
  r/anon/ 配下は30日で自動削除 (W3-2 の匿名結果ポリシーの下地)
- CloudFront (OAC 経由でのみ S3 に到達、HTTPS 強制)。独自ドメインは後付け
  (追加時は ACM 証明書 us-east-1 + エイリアスをここに足す)
- AWS Budgets: 月額の実績アラート (メールは -c alert_email= で指定。未指定なら作らない)
"""

from aws_cdk import (
    CfnOutput,
    Duration,
    RemovalPolicy,
    Stack,
    aws_budgets as budgets,
    aws_cloudfront as cloudfront,
    aws_cloudfront_origins as origins,
    aws_s3 as s3,
)
from constructs import Construct

MONTHLY_BUDGET_USD = 20  # 想定コスト数百円に対する天井 (~3,000円)


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
                )
            ],
        )

        distribution = cloudfront.Distribution(
            self,
            "Cdn",
            comment="gtfs-semdiff results",
            default_behavior=cloudfront.BehaviorOptions(
                origin=origins.S3BucketOrigin.with_origin_access_control(bucket),
                viewer_protocol_policy=cloudfront.ViewerProtocolPolicy.REDIRECT_TO_HTTPS,
                cache_policy=cloudfront.CachePolicy.CACHING_OPTIMIZED,
                compress=True,
            ),
            # 日本を含むアジアのエッジまで (ALL より安い)
            price_class=cloudfront.PriceClass.PRICE_CLASS_200,
        )

        alert_email = self.node.try_get_context("alert_email")
        if alert_email:
            budgets.CfnBudget(
                self,
                "MonthlyBudget",
                budget=budgets.CfnBudget.BudgetDataProperty(
                    budget_name="gtfs-semdiff-monthly",
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
