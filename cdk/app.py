#!/usr/bin/env python3
"""CDK app entrypoint for Kinga Maji.

Account and region are resolved from the environment so the repo is not hardwired
to one AWS account. Set CDK_DEPLOY_ACCOUNT (or CDK_DEFAULT_ACCOUNT) and
CDK_DEPLOY_REGION. The simi-ops profile has no default region, so a region is
always supplied explicitly (defaults to us-east-1).
"""
import os

from aws_cdk import App, Environment

from kinga_stack import KingaStack

app = App()

account = os.environ.get("CDK_DEPLOY_ACCOUNT") or os.environ.get("CDK_DEFAULT_ACCOUNT")
region = (
    os.environ.get("CDK_DEPLOY_REGION")
    or os.environ.get("CDK_DEFAULT_REGION")
    or "us-east-1"
)

KingaStack(
    app,
    "KingaMajiStack",
    env=Environment(account=account, region=region),
)

app.synth()
