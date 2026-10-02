#!/usr/bin/env python3
"""CDK app entrypoint for Kinga Maji.

Account and region are pinned explicitly: the simi-ops profile has no default
region, so the environment MUST be hardcoded here (plan.md).
"""
from aws_cdk import App, Environment

from kinga_stack import KingaStack

app = App()

KingaStack(
    app,
    "KingaMajiStack",
    env=Environment(account="888577033943", region="us-east-1"),
)

app.synth()
