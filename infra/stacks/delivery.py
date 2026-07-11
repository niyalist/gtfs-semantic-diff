"""W3-0/W3-1: 結果配信基盤 + ジョブ API (設計: docs/design/web.md)。

- S3 バケット (非公開・全パブリックアクセスブロック)。結果 HTML を r/{id}.html に置く。
  r/anon/ と uploads/ は自動削除 (匿名30日・アップロード7日)
- CloudFront (OAC 経由でのみ S3 に到達、HTTPS 強制)。/api/* は HTTP API へ、
  / は入力 UI (web/index.html)。独自ドメインは後付け
- ジョブ実行 (W3-1): 同一コンテナイメージの Lambda 2関数 (api / worker)。
  api がジョブを DynamoDB に登録し worker を非同期起動、worker が compare →
  HTML を S3 へ書く。UI はポーリングで完成を待つ
- AWS Budgets: 月額の実績アラート (メールは -c alert_email= で指定。未指定なら作らない)
- ログイン (W3-2b): Cognito UserPool + Hosted UI + Google IdP。自前パスワードは
  持たない。Google IdP は -c google_client_id=... 指定時のみ作成 (client secret は
  Secrets Manager の gtfs-semdiff/google-oauth から)。IdP 未接続でも他機能は動く。
  /api/me/* だけ JWT オーソライザで保護し、匿名機能はそのまま
"""

from aws_cdk import (
    CfnOutput,
    Duration,
    RemovalPolicy,
    SecretValue,
    Size,
    Stack,
    aws_apigatewayv2 as apigwv2,
    aws_apigatewayv2_authorizers as apigw_authorizers,
    aws_apigatewayv2_integrations as apigw_integrations,
    aws_budgets as budgets,
    aws_cloudfront as cloudfront,
    aws_cloudfront_origins as origins,
    aws_cognito as cognito,
    aws_dynamodb as dynamodb,
    aws_iam as iam,
    aws_lambda as lambda_,
    aws_s3 as s3,
    aws_ses as ses,
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

        # ログインユーザーのデータ (W3-2b): pk=user_id, sk=run#…/zip#… の単一テーブル
        userdata_table = dynamodb.Table(
            self,
            "UserData",
            partition_key=dynamodb.Attribute(
                name="user_id", type=dynamodb.AttributeType.STRING
            ),
            sort_key=dynamodb.Attribute(
                name="sk", type=dynamodb.AttributeType.STRING
            ),
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
            removal_policy=RemovalPolicy.RETAIN,  # 履歴・保存 zip 台帳は消さない
        )

        # フィードバック (W3-2c): {結果の版固定 URL, event_id, 記述}。恒久保存
        feedback_table = dynamodb.Table(
            self,
            "Feedback",
            partition_key=dynamodb.Attribute(
                name="feedback_id", type=dynamodb.AttributeType.STRING
            ),
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
            removal_policy=RemovalPolicy.RETAIN,
        )

        image_dir = "../"  # ビルドコンテキスト = リポジトリルート (.dockerignore 参照)
        common_env = {
            "RESULTS_BUCKET": bucket.bucket_name,
            "JOBS_TABLE": jobs_table.table_name,
            "USERDATA_TABLE": userdata_table.table_name,
            "FEEDBACK_TABLE": feedback_table.table_name,
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
            # 大規模フィード (産交バス: stop_times 55万行×2世代) に耐えるサイズ。
            # Lambda は memory に比例して vCPU も増える。4096 はこのアカウントの
            # クォータ (3008MB) を超えたため上限値を使う (引き上げ申請は任意)
            memory_size=3008,
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
        # lazy 再生成の判定で版台帳 (r/{pair}/index.json) を読む (W3-2a)
        bucket.grant_read(api_fn, "r/*")
        # 削除機能 (W3-2b): 本人のアップロード結果と保存 zip のみ
        bucket.grant_delete(api_fn, "r/u/*")
        bucket.grant_delete(api_fn, "userzips/*")
        jobs_table.grant_read_write_data(worker_fn)
        jobs_table.grant_read_write_data(api_fn)
        userdata_table.grant_read_write_data(worker_fn)
        userdata_table.grant_read_write_data(api_fn)
        feedback_table.grant_read_write_data(api_fn)
        worker_fn.grant_invoke(api_fn)

        # フィードバックの通知先 (SES)。メールは -c feedback_email= で指定。
        # sandbox のままでよい (自分宛て送信のみ)。未指定なら記録のみ
        feedback_email = self.node.try_get_context("feedback_email") or ""
        if feedback_email:
            ses.EmailIdentity(
                self, "FeedbackEmail", identity=ses.Identity.email(feedback_email)
            )
            api_fn.add_environment("FEEDBACK_EMAIL", feedback_email)
            api_fn.add_to_role_policy(iam.PolicyStatement(
                actions=["ses:SendEmail"],
                resources=[
                    f"arn:aws:ses:{self.region}:{self.account}:identity/"
                    f"{feedback_email}"
                ],
            ))

        # --- ログイン (W3-2b): Cognito + Google IdP ---
        user_pool = cognito.UserPool(
            self,
            "Users",
            self_sign_up_enabled=False,  # 自前パスワードユーザーは作らない
            sign_in_aliases=cognito.SignInAliases(email=True),
            removal_policy=RemovalPolicy.RETAIN,
        )
        pool_domain = user_pool.add_domain(
            "HostedUi",
            cognito_domain=cognito.CognitoDomainOptions(
                domain_prefix="gtfs-semdiff"
            ),
        )
        google_client_id = self.node.try_get_context("google_client_id") or ""
        idps = []
        if google_client_id:
            google_idp = cognito.UserPoolIdentityProviderGoogle(
                self,
                "Google",
                user_pool=user_pool,
                client_id=google_client_id,
                # 事前に: aws secretsmanager create-secret --name gtfs-semdiff/google-oauth
                #   --secret-string '<client secret 文字列そのまま>'
                client_secret_value=SecretValue.secrets_manager(
                    "gtfs-semdiff/google-oauth"
                ),
                scopes=["openid", "email"],
                attribute_mapping=cognito.AttributeMapping(
                    email=cognito.ProviderAttribute.GOOGLE_EMAIL
                ),
            )
            idps.append(cognito.UserPoolClientIdentityProvider.GOOGLE)

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

        # Hosted UI からの戻り先 = CloudFront (distribution 作成後にクライアントを作る)
        site_url = f"https://{distribution.distribution_domain_name}/"
        client_kwargs = dict(
            o_auth=cognito.OAuthSettings(
                flows=cognito.OAuthFlows(authorization_code_grant=True),  # + PKCE
                scopes=[cognito.OAuthScope.OPENID, cognito.OAuthScope.EMAIL],
                callback_urls=[site_url],
                logout_urls=[site_url],
            ),
            generate_secret=False,  # SPA (PKCE) なのでシークレットなし
            prevent_user_existence_errors=True,
        )
        if idps:
            client_kwargs["supported_identity_providers"] = idps
        app_client = user_pool.add_client("Web", **client_kwargs)
        if google_client_id:
            app_client.node.add_dependency(google_idp)

        # /api/me/* だけ JWT (Cognito ID トークン) で保護。他は匿名のまま
        jwt_authorizer = apigw_authorizers.HttpJwtAuthorizer(
            "MeAuth",
            f"https://cognito-idp.{self.region}.amazonaws.com/"
            f"{user_pool.user_pool_id}",
            jwt_audience=[app_client.user_pool_client_id],
        )
        me_integration = apigw_integrations.HttpLambdaIntegration(
            "MeIntegration", api_fn
        )
        for path in ("/api/me", "/api/me/{proxy+}"):
            http_api.add_routes(
                path=path,
                methods=[apigwv2.HttpMethod.ANY],
                integration=me_integration,
                authorizer=jwt_authorizer,
            )
        cognito_domain = (
            f"{pool_domain.domain_name}.auth.{self.region}.amazoncognito.com"
        )
        api_fn.add_environment("COGNITO_DOMAIN", cognito_domain)
        api_fn.add_environment("COGNITO_CLIENT_ID", app_client.user_pool_client_id)
        api_fn.add_environment("GOOGLE_LOGIN", "1" if google_client_id else "")

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
        CfnOutput(self, "UserDataTable", value=userdata_table.table_name)
        CfnOutput(self, "UserPoolId", value=user_pool.user_pool_id)
        CfnOutput(self, "CognitoDomain", value=cognito_domain)
        CfnOutput(self, "WebClientId", value=app_client.user_pool_client_id)
