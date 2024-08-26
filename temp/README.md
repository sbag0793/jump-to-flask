# VPC
3 가용 영역
# RDS
데이터베이스 제약 조건
# EKS
5 Addon Node
# Bastion
aws eks update-kubeconfig --region ap-northeast-2 --name wsi-eks-cluster
## RDS Setting
# Application & Fluent-bit
## Application Build
```Dockerfile
FROM public.ecr.aws/docker/library/alpine

WORKDIR /myapp

COPY <애플리케이션 바이너리> .

RUN apk add --update \
    curl \
    && rm -rf /var/cache/apk/*

CMD ["sh", "-c", "./app 2>&1 > app.log"]
```
## Fluent-bit Setting
```bash
export CLUSTER_NAME="wsi-eks-cluster"
export AWS_REGION="ap-northeast-2"
export ACCOUNT_ID="$(aws sts get-caller-identity --query Account --output text)"
```

로그 생성 위치는 /myapp/logs
fluent-bit 서비스 어카운트 생성
```bash
eksctl utils associate-iam-oidc-provider --cluster=${CLUSTER_NAME} --approve
eksctl create iamserviceaccount --cluster=${CLUSTER_NAME} \
--name=fluent-bit \
--namespace=myapp \
--attach-policy-arn=arn:aws:iam::aws:policy/CloudWatchAgentServerPolicy \
--role-name=wsi-eks-fluentbit-role \
--approve
```

```bash
FluentBitHttpPort='2020'
FluentBitReadFromHead='Off'
[[ ${FluentBitReadFromHead} = 'On' ]] && FluentBitReadFromTail='Off'|| FluentBitReadFromTail='On'
[[ -z ${FluentBitHttpPort} ]] && FluentBitHttpServer='Off' || FluentBitHttpServer='On'
kubectl create configmap fluent-bit-cluster-info \
--from-literal=cluster.name=${CLUSTER_NAME} \
--from-literal=http.server=${FluentBitHttpServer} \
--from-literal=http.port=${FluentBitHttpPort} \
--from-literal=read.head=${FluentBitReadFromHead} \
--from-literal=read.tail=${FluentBitReadFromTail} \
--from-literal=logs.region=${AWS_REGION} -n myapp
```
```yaml
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: fluent-bit-role
  namespace: myapp
rules:
  - nonResourceURLs:
      - /metrics
    verbs:
      - get
  - apiGroups: [""]
    resources:
      - namespaces
      - pods
      - pods/logs
      - nodes
      - nodes/proxy
    verbs: ["get", "list", "watch"]
---
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRoleBinding
metadata:
  name: fluent-bit-role-binding
roleRef:
  apiGroup: rbac.authorization.k8s.io
  kind: ClusterRole
  name: fluent-bit-role
subjects:
  - kind: ServiceAccount
    name: fluent-bit
    namespace: myapp
---
apiVersion: v1
kind: ConfigMap
metadata:
  name: fluent-bit-config
  namespace: myapp
  labels:
    k8s-app: fluent-bit
data:
  fluent-bit.conf: |
    [SERVICE]
        Flush                     5
        Grace                     30
        Log_Level                 info
        Daemon                    off
        Parsers_File              parsers.conf
        HTTP_Server               ${HTTP_SERVER}
        HTTP_Listen               0.0.0.0
        HTTP_Port                 ${HTTP_PORT}
        storage.path              /var/fluent-bit/state/flb-storage/
        storage.sync              normal
        storage.checksum          off
        storage.backlog.mem_limit 5M

    @INCLUDE application-log.conf

  application-log.conf: |
    [INPUT]
        Name                tail
        Tag                 application.*
        Path                /myapp/logs/*.log
        multiline.parser    docker, cri
        DB                  /var/fluent-bit/state/flb_log.db
        Mem_Buf_Limit       5MB
        Skip_Long_Lines     On
        Refresh_Interval    10
        Read_from_Head      ${READ_FROM_HEAD}

    [OUTPUT]
        Name                cloudwatch_logs
        Match               application.*
        region              ${AWS_REGION}
        log_group_name      /wsi/token
        log_stream_prefix     token-${HOST_NAME}
        auto_create_group   true

  parsers.conf: |
    [PARSER]
        Name                syslog
        Format              regex
        Regex               ^(?<time>[^ ]* {1,2}[^ ]* [^ ]*) (?<host>[^ ]*) (?<ident>[a-zA-Z0-9_\/\.\-]*)(?:\[(?<pid>[0-9]+)\])?(?:[^\:]*\:)? *(?<message>.*)$
        Time_Key            time
        Time_Format         %b %d %H:%M:%S
```

## Token Deployment
```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: token-deployment
  labels:
    app: token
  namespace: myapp
spec:
  selector:
    matchLabels:
      app: token
  template:
    metadata:
      labels:
        app: token
      name: token-pod
    spec:
      containers:
      - name: token-container
        image: <IMAGE_REPO>
        ports:
        - containerPort: 8080
        volumeMounts:
        - name: myapp
          mountPath: /myapp/logs
        readinessProbe:
          httpGet:
            path: /healthcheck
            port: 8080
          periodSeconds: 10
        livenessProbe:
          httpGet:
            path: /healthcheck
            port: 8080
          periodSeconds: 10
      - name: fluent-bit
        image: public.ecr.aws/aws-observability/aws-for-fluent-bit:stable
        imagePullPolicy: Always
        env:
        - name: AWS_REGION
          valueFrom:
            configMapKeyRef:
              name: fluent-bit-cluster-info
              key: logs.region
        - name: CLUSTER_NAME
          valueFrom:
            configMapKeyRef:
              name: fluent-bit-cluster-info
              key: cluster.name
        - name: HTTP_SERVER
          valueFrom:
            configMapKeyRef:
              name: fluent-bit-cluster-info
              key: http.server
        - name: HTTP_PORT
          valueFrom:
            configMapKeyRef:
              name: fluent-bit-cluster-info
              key: http.port
        - name: READ_FROM_HEAD
          valueFrom:
            configMapKeyRef:
              name: fluent-bit-cluster-info
              key: read.head
        - name: READ_FROM_TAIL
          valueFrom:
            configMapKeyRef:
              name: fluent-bit-cluster-info
              key: read.tail
        - name: HOST_NAME
          valueFrom:
            fieldRef:
              fieldPath: spec.nodeName
        - name: HOSTNAME
          valueFrom:
            fieldRef:
              apiVersion: v1
              fieldPath: metadata.name
        - name: CI_VERSION
          value: "k8s/1.3.26"
        volumeMounts:
        - name: fluentbitstate
          mountPath: /var/fluent-bit/state
        - name: varlog
          mountPath: /var/log
          readOnly: true
        - name: varlibdockercontainers
          mountPath: /var/lib/docker/containers
          readOnly: true
        - name: fluent-bit-config
          mountPath: /fluent-bit/etc/
        - name: runlogjournal
          mountPath: /run/log/journal
          readOnly: true
        - name: dmesg
          mountPath: /var/log/dmesg
          readOnly: true
        - name: myapp
          mountPath: /myapp/logs
      terminationGracePeriodSeconds: 10
      hostNetwork: true
      dnsPolicy: ClusterFirstWithHostNet
      volumes:
      - name: fluentbitstate
        hostPath:
          path: /var/fluent-bit/state
      - name: varlog
        hostPath:
          path: /var/log
      - name: varlibdockercontainers
        hostPath:
          path: /var/lib/docker/containers
      - name: fluent-bit-config
        configMap:
          name: fluent-bit-config
      - name: runlogjournal
        hostPath:
          path: /run/log/journal
      - name: dmesg
        hostPath:
          path: /var/log/dmesg
      - name: myapp
        emptyDir: {}
      serviceAccountName: fluent-bit
      nodeSelector:
        node: app
      toleratins:
      - key: key
        value: value
---
apiVersion: v1
kind: Service
metadata:
  name: token-service
  namespace: myapp
spec:
  type: NodePort
  selector:
    app: token
  ports:
    - port: 80
      targetPort: 8080
```
# Ingress
```bash
curl -O https://raw.githubusercontent.com/kubernetes-sigs/aws-load-balancer-controller/v2.7.2/docs/install/iam_policy.json
aws iam create-policy \
    --policy-name AWSLoadBalancerControllerIAMPolicy \
    --policy-document file://iam_policy.json
eksctl create iamserviceaccount \
  --cluster=${CLUSTER_NAME} \
  --namespace=kube-system \
  --name=aws-load-balancer-controller \
  --role-name AmazonEKSLoadBalancerControllerRole \
  --attach-policy-arn=arn:aws:iam::${ACCOUNT_ID}:policy/AWSLoadBalancerControllerIAMPolicy \
  --approve
helm repo add eks https://aws.github.io/eks-charts
helm repo update eks
helm install aws-load-balancer-controller eks/aws-load-balancer-controller \
  -n kube-system \
  --set clusterName=wsi-eks-cluster \
  --set serviceAccount.create=false \
  --set serviceAccount.name=aws-load-balancer-controller \
  --set region=ap-northeast-2 \
  --set vpcId=<VPC_ID>
```
```yaml
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  namespace: myapp
  name: myapp
  annotations:
    alb.ingress.kubernetes.io/load-balancer-name: wsi-app-alb
    alb.ingress.kubernetes.io/scheme: internet-facing
    alb.ingress.kubernetes.io/subnets: <SUBNET_ARNS>
    alb.ingress.kubernetes.io/security-groups: <SECURITY_GROUP_ARNS>
    alb.ingress.kubernetes.io/target-type: instance
    alb.ingress.kubernetes.io/healthcheck-path: /healthcheck
    alb.ingress.kubernetes.io/target-node-labels: node=app
    alb.ingress.kubernetes.io/actions.response-404: >
      {"type":"fixed-response","fixedResponseConfig":{"contentType":"text/plain","statusCode":"404","messageBody":"Unhealthy request"}}
spec:
  ingressClassName: alb
  rules:
    - http:
        paths:
        - path: /v1/token
          pathType: Exact
          backend:
            service:
              name: token-service
              port:
                number: 80
        - path: /v1/employee
          pathType: Exact
          backend:
            service:
              name: employee-service
              port:
                number: 80
          - path: /
            pathType: Prefix
            backend:
              service:
                name: response-404
                port:
                  name: use-annotation
```
# Metrics Server
kubectl apply -f https://github.com/kubernetes-sigs/metrics-server/releases/latest/download/components.yaml
# HPA
```yaml
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  namespace: myapp
  name: token-hpa
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: token-deployment
  minReplicas: 4
  maxReplicas: 100
  metrics:
  - type: Resource
    resource:
      name: cpu
      target:
        type: Utilization
        averageUtilization: 70
```
# Karpenter
```bash
export KARPENTER_NAMESPACE="kube-system"
export KARPENTER_VERSION="0.37.0"
export K8S_VERSION="1.30"

export AWS_PARTITION="aws" # if you are not using standard partitions, you may need to configure to aws-cn / aws-us-gov
export CLUSTER_NAME="${USER}-karpenter-demo"
export AWS_DEFAULT_REGION="us-west-2"
export AWS_ACCOUNT_ID="$(aws sts get-caller-identity --query Account --output text)"
export TEMPOUT="$(mktemp)"
export ARM_AMI_ID="$(aws ssm get-parameter --name /aws/service/eks/optimized-ami/${K8S_VERSION}/amazon-linux-2-arm64/recommended/image_id --query Parameter.Value --output text)"
export AMD_AMI_ID="$(aws ssm get-parameter --name /aws/service/eks/optimized-ami/${K8S_VERSION}/amazon-linux-2/recommended/image_id --query Parameter.Value --output text)"
export GPU_AMI_ID="$(aws ssm get-parameter --name /aws/service/eks/optimized-ami/${K8S_VERSION}/amazon-linux-2-gpu/recommended/image_id --query Parameter.Value --output text)"



curl -fsSL https://raw.githubusercontent.com/aws/karpenter-provider-aws/v"${KARPENTER_VERSION}"/website/content/en/preview/getting-started/getting-started-with-karpenter/cloudformation.yaml  > "${TEMPOUT}" \
&& aws cloudformation deploy \
  --stack-name "Karpenter-${CLUSTER_NAME}" \
  --template-file "${TEMPOUT}" \
  --capabilities CAPABILITY_NAMED_IAM \
  --parameter-overrides "ClusterName=${CLUSTER_NAME}"

eksctl create iamidentitymapping \
  --username system:node:{{EC2PrivateDNSName}} \
  --cluster "${CLUSTER_NAME}" \
  --arn "arn:aws:iam::${AWS_ACCOUNT_ID}:role/KarpenterNodeRole-${CLUSTER_NAME}" \
  --group system:bootstrappers \
  --group system:nodes

eksctl create iamserviceaccount \
  --cluster "${CLUSTER_NAME}" --name karpenter --namespace karpenter \
  --role-name "${CLUSTER_NAME}-karpenter" \
  --attach-policy-arn "arn:aws:iam::${AWS_ACCOUNT_ID}:policy/KarpenterControllerPolicy-${CLUSTER_NAME}" \
  --role-only \
  --approve

KARPENTER_IAM_ROLE_ARN="arn:aws:iam::${AWS_ACCOUNT_ID}:role/${CLUSTER_NAME}-karpenter"
helm upgrade karpenter oci://public.ecr.aws/karpenter/karpenter \
  --install --version 1.0.0 --namespace karpenter --create-namespace \
  --set serviceAccount.annotations."eks\.amazonaws\.com/role-arn"=${KARPENTER_IAM_ROLE_ARN} \
  --set settings.clusterName=${CLUSTER_NAME} \
  --set settings.interruptionQueueName=${CLUSTER_NAME} \
  --set controller.resources.requests.cpu=1 \
  --set controller.resources.requests.memory=1Gi \
  --set controller.resources.limits.cpu=1 \
  --set controller.resources.limits.memory=1Gi \
  --wait
```
# CloudFront
# Monitoring
## 1 minute StatusCode (4xx, 5xx)
## Error Log (4xx, 5xx)
# locust Test?
```python
from locust import task, FastHttpUser

class MyUser(FastHttpUser):
    @task
    def postToken(self):
        headers = {"Content-Type": 'application/json'}
        payload = {'length': 100}
        self.client.post('/v1/token', headers=headers, json=payload)

```