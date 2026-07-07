#!/usr/bin/env python3
"""gtfs-semdiff Web 公開 (roadmap W3) の CDK アプリ。

W3-0: 配信基盤 (S3 + CloudFront OAC + Budgets)。
デプロイ: cd infra && AWS_PROFILE=<profile> npx aws-cdk deploy \
            -c alert_email=<mail> --outputs-file outputs.json
"""
import os

import aws_cdk as cdk

from stacks.delivery import DeliveryStack

app = cdk.App()
DeliveryStack(
    app,
    "GtfsSemdiffDelivery",
    env=cdk.Environment(
        account=os.environ.get("CDK_DEFAULT_ACCOUNT"),
        region=os.environ.get("CDK_DEFAULT_REGION", "ap-northeast-1"),
    ),
)
app.synth()
