import json

import pulumi
from pulumi_aws import ec2, lb, cloudwatch, ecs, iam

from networking import Networking
from input_schemas import SubnetType, DjangoServiceCfg
from .repository import Repository
from .image import Image
from dbs.rds import RDS


class ECSService:
    def __init__(
        self,
        networking: Networking,
        django_srv_cfg: DjangoServiceCfg,
        roles: dict[str, iam.Role],
    ):
        self.networking = networking
        self.django_srv_cfg = django_srv_cfg
        self.roles = roles
        self.create_resources()

    def create_resources(self):
        self.create_networking()
        self.create_db()
        self.create_ecs_service()

    def create_networking(self):
        SERVICE_NAME = self.django_srv_cfg.service_name.replace("_", "-")
        LB_PORT = self.django_srv_cfg.backend_cfg.lb_port

        lb_sg = ec2.SecurityGroup(
            f"{SERVICE_NAME}-lb-sg",
            name=f"{SERVICE_NAME}-lb-sg",
            description="Controls access to the ALB",
            vpc_id=self.networking.get_vpc_id(),
            ingress=[
                ec2.SecurityGroupIngressArgs(
                    from_port=LB_PORT,
                    to_port=LB_PORT,
                    protocol="tcp",
                    cidr_blocks=["0.0.0.0/0"],
                ),
            ],
            egress=[
                ec2.SecurityGroupEgressArgs(
                    from_port=0,
                    to_port=0,
                    protocol="-1",
                    cidr_blocks=["0.0.0.0/0"],
                ),
            ],
            tags={
                "Name": f"{SERVICE_NAME}-lb-sg",
            },
        )

        self.ecs_sg = ec2.SecurityGroup(
            f"{SERVICE_NAME}-sg",
            name=f"{SERVICE_NAME}-ecs-sg",
            description="Controls access to the ECS Service",
            vpc_id=self.networking.get_vpc_id(),
            ingress=[
                ec2.SecurityGroupIngressArgs(
                    from_port=0,
                    to_port=0,
                    protocol="-1",
                    security_groups=[lb_sg.id],
                ),
            ],
            egress=[
                ec2.SecurityGroupEgressArgs(
                    from_port=0,
                    to_port=0,
                    protocol="-1",
                    cidr_blocks=["0.0.0.0/0"],
                ),
            ],
            tags={
                "Name": f"{SERVICE_NAME}-ecs-sg",
            },
        )

        django_lb = lb.LoadBalancer(
            f"{SERVICE_NAME}-lb",
            name=f"{SERVICE_NAME}-lb",
            load_balancer_type="application",
            internal=False,
            security_groups=[lb_sg.id],
            subnets=[*self.networking.get_subnet_ids(SubnetType.PUBLIC)],
        )

        self.django_tg = lb.TargetGroup(
            f"{SERVICE_NAME}-service-tg",
            name=f"{SERVICE_NAME}-service-tg",
            port=LB_PORT,
            protocol="HTTP",
            vpc_id=self.networking.get_vpc_id(),
            target_type="ip",
            health_check=lb.TargetGroupHealthCheckArgs(
                path="/ping/",
                port="traffic-port",
                healthy_threshold=5,
                unhealthy_threshold=2,
                timeout=2,
                interval=5,
                matcher="200",
            ),
        )

        lb.Listener(
            f"{SERVICE_NAME}-lb-listener",
            load_balancer_arn=django_lb.arn,
            port=LB_PORT,
            default_actions=[
                lb.ListenerDefaultActionArgs(
                    type="forward",
                    target_group_arn=self.django_tg.arn,
                ),
            ],
        )

    def create_db(self):
        self.db = RDS(self.networking, self.ecs_sg, self.django_srv_cfg)

    def create_ecs_service(self):
        SERVICE_NAME = self.django_srv_cfg.service_name
        CONT_PORT = self.django_srv_cfg.backend_cfg.container_port

        repository = Repository(f"{SERVICE_NAME}-repository")
        image = Image(
            SERVICE_NAME,
            self.django_srv_cfg.django_project,
            repository.get_repository(),
        )
        image_uri = image.push_image("0.0.1")

        django_log_group = cloudwatch.LogGroup(
            f"{SERVICE_NAME}-log-group",
            name=f"/ecs/{SERVICE_NAME}",
            retention_in_days=30,
        )

        ecs_cluster = ecs.Cluster(
            f"{SERVICE_NAME}-cluster", name=f"{SERVICE_NAME}-cluster"
        )

        container_definitions_template = pulumi.Output.all(
            image_uri=image_uri,
            log_group_name=django_log_group.name,
            host=self.db.get_host(),
        ).apply(
            lambda args: json.dumps(
                [
                    {
                        "name": SERVICE_NAME,
                        "image": args["image_uri"],
                        "essential": True,
                        "cpu": 10,
                        "memory": 512,
                        "portMappings": [
                            {
                                "containerPort": CONT_PORT,
                                "protocol": "tcp",
                            }
                        ],
                        "command": [SERVICE_NAME, str(CONT_PORT)],
                        "environment": [
                            {
                                "name": "ENVIRONMENT",
                                "value": "PROD",
                            },
                            {
                                "name": "DB_HOST",
                                "value": args["host"],
                            },
                        ],
                        "logConfiguration": {
                            "logDriver": "awslogs",
                            "options": {
                                "awslogs-group": args["log_group_name"],
                                "awslogs-region": "eu-west-1",
                                "awslogs-stream-prefix": f"{SERVICE_NAME}-log-stream",
                            },
                        },
                    }
                ]
            )
        )

        ecs_task_definition = ecs.TaskDefinition(
            f"{SERVICE_NAME}-tf",
            family=SERVICE_NAME,
            network_mode="awsvpc",
            requires_compatibilities=["FARGATE"],
            cpu=self.django_srv_cfg.backend_cfg.cpu,
            memory=self.django_srv_cfg.backend_cfg.memory,
            execution_role_arn=self.roles["ecs_execution_role"].arn,
            task_role_arn=self.roles["ecs_task_role"].arn,
            container_definitions=container_definitions_template,
        )

        ecs.Service(
            f"{SERVICE_NAME}-service",
            name=f"{SERVICE_NAME}-service",
            cluster=ecs_cluster.id,
            task_definition=ecs_task_definition.arn,
            launch_type="FARGATE",
            desired_count=self.django_srv_cfg.backend_cfg.desired_count,
            network_configuration=ecs.ServiceNetworkConfigurationArgs(
                subnets=[
                    *self.networking.get_subnet_ids(SubnetType.PRIVATE),
                ],
                security_groups=[
                    self.ecs_sg.id,
                ],
                assign_public_ip=True,
            ),
            load_balancers=[
                ecs.ServiceLoadBalancerArgs(
                    target_group_arn=self.django_tg.arn,
                    container_name=SERVICE_NAME,
                    container_port=CONT_PORT,
                )
            ],
        )
