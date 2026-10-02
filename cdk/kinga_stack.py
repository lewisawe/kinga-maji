"""Kinga Maji CDK stack.

Serverless flood-depth reporting app:
  DynamoDB (reports) + Python Lambda (vendored engine, no Docker bundling)
  + HTTP API (open CORS) + SNS topic + S3/CloudFront static site.

The Lambda asset dir (../lambda) must already contain handler.py and a vendored
depth_engine.py before synth; the deploy script re-vendors the engine first.
"""
import os

from aws_cdk import (
    CfnOutput,
    Duration,
    RemovalPolicy,
    Stack,
    aws_apigatewayv2 as apigwv2,
    aws_apigatewayv2_integrations as apigw_integrations,
    aws_cloudfront as cloudfront,
    aws_cloudfront_origins as origins,
    aws_dynamodb as dynamodb,
    aws_events as events,
    aws_events_targets as targets,
    aws_iam as iam,
    aws_lambda as lambda_,
    aws_s3 as s3,
    aws_s3_deployment as s3deploy,
    aws_sns as sns,
)
from constructs import Construct

HERE = os.path.dirname(__file__)
LAMBDA_ASSET = os.path.join(HERE, "..", "lambda")
WEB_ASSET = os.path.join(HERE, "..", "web")

MODEL_ID = "amazon.nova-lite-v1:0"
# Bedrock foundation-model ARNs are region-scoped with an EMPTY account segment.
BEDROCK_MODEL_ARNS = [
    "arn:aws:bedrock:us-east-1::foundation-model/amazon.nova-lite-v1:0",
    "arn:aws:bedrock:us-east-1::foundation-model/amazon.nova-pro-v1:0",
]


class KingaStack(Stack):
    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # --- DynamoDB: reports table -------------------------------------
        table = dynamodb.Table(
            self,
            "ReportsTable",
            partition_key=dynamodb.Attribute(
                name="settlement", type=dynamodb.AttributeType.STRING
            ),
            sort_key=dynamodb.Attribute(
                name="timestamp", type=dynamodb.AttributeType.STRING
            ),
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
            removal_policy=RemovalPolicy.DESTROY,
        )

        # --- SNS: alert topic --------------------------------------------
        topic = sns.Topic(self, "AlertsTopic", display_name="kinga-alerts")

        # --- Lambda: analyze handler (engine vendored, NO Docker bundling)
        fn = lambda_.Function(
            self,
            "AnalyzeFunction",
            runtime=lambda_.Runtime.PYTHON_3_13,
            handler="handler.handler",
            code=lambda_.Code.from_asset(LAMBDA_ASSET),
            timeout=Duration.seconds(30),
            memory_size=512,
            environment={
                "TABLE_NAME": table.table_name,
                "SNS_TOPIC_ARN": topic.topic_arn,
                "MODEL_ID": MODEL_ID,
            },
        )

        # --- IAM grants ---------------------------------------------------
        table.grant_read_write_data(fn)
        topic.grant_publish(fn)
        fn.add_to_role_policy(
            iam.PolicyStatement(
                actions=["bedrock:InvokeModel"],
                resources=BEDROCK_MODEL_ARNS,
            )
        )

        # --- HTTP API (open CORS) ----------------------------------------
        http_api = apigwv2.HttpApi(
            self,
            "KingaApi",
            api_name="kinga-api",
            cors_preflight=apigwv2.CorsPreflightOptions(
                allow_origins=["*"],
                allow_methods=[apigwv2.CorsHttpMethod.ANY],
                allow_headers=["*"],
            ),
        )
        integration = apigw_integrations.HttpLambdaIntegration(
            "AnalyzeIntegration", fn
        )
        routes = [
            ("/analyze", apigwv2.HttpMethod.POST),
            ("/reports", apigwv2.HttpMethod.GET),
            ("/seed", apigwv2.HttpMethod.POST),
            ("/health", apigwv2.HttpMethod.GET),
            # Autonomous watcher (ADDITIVE): read latest alerts + run a cycle.
            ("/alerts", apigwv2.HttpMethod.GET),
            ("/watch", apigwv2.HttpMethod.POST),
        ]
        for path, method in routes:
            http_api.add_routes(path=path, methods=[method], integration=integration)

        # --- EventBridge: hourly autonomous watcher (ADDITIVE) ------------
        # Invoke the SAME Lambda on a synthetic /watch event every hour. The
        # event shape matches the handler's HTTP-API-v2 routing (rawPath +
        # requestContext.http.method), so the scheduled invoke runs _watch().
        # add_target(LambdaFunction(...)) wires the lambda:InvokeFunction
        # permission automatically — no manual Permission needed. DynamoDB RW is
        # already granted to fn above; alerts reuse that grant.
        schedule_rule = events.Rule(
            self,
            "WatcherSchedule",
            schedule=events.Schedule.rate(Duration.hours(1)),
        )
        schedule_rule.add_target(
            targets.LambdaFunction(
                fn,
                event=events.RuleTargetInput.from_object(
                    {
                        "rawPath": "/watch",
                        "requestContext": {"http": {"method": "POST"}},
                    }
                ),
            )
        )

        # --- S3 + CloudFront static site ---------------------------------
        site_bucket = s3.Bucket(
            self,
            "WebBucket",
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            removal_policy=RemovalPolicy.DESTROY,
            auto_delete_objects=True,
        )

        distribution = cloudfront.Distribution(
            self,
            "WebDistribution",
            default_root_object="index.html",
            default_behavior=cloudfront.BehaviorOptions(
                origin=origins.S3BucketOrigin.with_origin_access_control(site_bucket),
                viewer_protocol_policy=cloudfront.ViewerProtocolPolicy.REDIRECT_TO_HTTPS,
            ),
        )

        s3deploy.BucketDeployment(
            self,
            "DeployWeb",
            sources=[s3deploy.Source.asset(WEB_ASSET)],
            destination_bucket=site_bucket,
            distribution=distribution,
            distribution_paths=["/*"],
        )

        # --- Outputs ------------------------------------------------------
        CfnOutput(
            self,
            "CloudFrontURL",
            value="https://" + distribution.distribution_domain_name,
        )
        CfnOutput(self, "ApiUrl", value=http_api.api_endpoint)
        CfnOutput(self, "TableName", value=table.table_name)
        CfnOutput(self, "TopicArn", value=topic.topic_arn)
