import yaml

from copy import deepcopy

deployment_manifest = yaml.safe_load(
    """---
apiVersion: apps/v1
kind: Deployment
metadata:
  name: nginx-demo
  namespace: secondary
spec:
  selector:
    matchLabels:
      app: nginx
  template:
    metadata:
      labels:
        app: nginx
    spec:
      containers:
      - name: nginx
        image: nginx:1.7.9
        ports:
        - containerPort: 80
"""
)

service_manifest = yaml.safe_load(
    """---
apiVersion: v1
kind: Service
metadata:
  name: nginx-demo
  namespace: secondary
spec:
  type: NodePort
  selector:
    app: nginx
  ports:
  - port: 80
    protocol: TCP
    targetPort: 80
"""
)

configmap_manifest = yaml.safe_load(
    """---
apiVersion: v1
kind: ConfigMap
metadata:
  name: nginx-demo
  namespace: secondary
data:
  nginx_config: "myconfig"
"""
)

nginx_manifest = [deployment_manifest, service_manifest, configmap_manifest]

# To be used to initialize spec.observer_schema
custom_deployment_observer_schema = yaml.safe_load(
    """---
apiVersion: apps/v1
kind: Deployment
metadata:
  name: nginx-demo
  namespace: null
spec:
  replicas: null
  selector:
    matchLabels:
      app: null
  template:
    metadata:
      labels:
        app: null
    spec:
      containers:
      - name: null
        image: null
        ports:
        - containerPort: null
        - observer_schema_list_min_length: 1
          observer_schema_list_max_length: 1
      - observer_schema_list_min_length: 1
        observer_schema_list_max_length: 1
"""
)

custom_service_observer_schema = yaml.safe_load(
    """---
apiVersion: v1
kind: Service
metadata:
  name: nginx-demo
  namespace: null
spec:
  type: null
  selector:
    app: null
  ports:
  - port: null
    targetPort: null
  - observer_schema_list_min_length: 0
    observer_schema_list_max_length: 2
"""
)

custom_configmap_observer_schema = yaml.safe_load(
    """---
apiVersion: v1
kind: ConfigMap
metadata:
  name: nginx-demo
  namespace: null
"""
)

custom_observer_schema = [
    custom_deployment_observer_schema,
    custom_service_observer_schema,
    custom_configmap_observer_schema,
]

# To be used to initialize status.mangled_observer_schema when the controller loop is
# not called in the test.
mangled_deployment_observer_schema = deepcopy(custom_deployment_observer_schema)
mangled_service_observer_schema = deepcopy(custom_service_observer_schema)
mangled_configmap_observer_schema = deepcopy(custom_configmap_observer_schema)

mangled_deployment_observer_schema["metadata"]["namespace"] = "secondary"
mangled_service_observer_schema["metadata"]["namespace"] = "secondary"
mangled_configmap_observer_schema["metadata"]["namespace"] = "secondary"

mangled_observer_schema = [
    mangled_deployment_observer_schema,
    mangled_service_observer_schema,
    mangled_configmap_observer_schema,
]


deployment_response = yaml.safe_load(
    """
apiVersion: apps/v1
kind: Deployment
metadata:
  annotations:
    deployment.kubernetes.io/revision: "1"
  creationTimestamp: "2019-11-11T12:01:05Z"
  generation: 1
  name: nginx-demo
  namespace: secondary
  resourceVersion: "8080030"
  selfLink: /apis/apps/v1/namespaces/secondary/deployments/nginx-demo
  uid: 047686e4-af52-4264-b2a4-2f82b890e809
spec:
  progressDeadlineSeconds: 600
  replicas: 1
  revisionHistoryLimit: 10
  selector:
    matchLabels:
      app: nginx
  strategy:
    rollingUpdate:
      maxSurge: 25%
      maxUnavailable: 25%
    type: RollingUpdate
  template:
    metadata:
      creationTimestamp: null
      labels:
        app: nginx
    spec:
      containers:
      - image: nginx:1.7.9
        imagePullPolicy: IfNotPresent
        name: nginx
        ports:
        - containerPort: 80
          protocol: TCP
        resources: {}
        terminationMessagePath: /dev/termination-log
        terminationMessagePolicy: File
      dnsPolicy: ClusterFirst
      restartPolicy: Always
      schedulerName: default-scheduler
      securityContext: {}
      terminationGracePeriodSeconds: 30
status:
  availableReplicas: 1
  conditions:
  - lastTransitionTime: "2019-11-11T12:01:07Z"
    lastUpdateTime: "2019-11-11T12:01:07Z"
    message: Deployment has minimum availability.
    reason: MinimumReplicasAvailable
    status: "True"
    type: Available
  - lastTransitionTime: "2019-11-11T12:01:05Z"
    lastUpdateTime: "2019-11-11T12:01:07Z"
    message: ReplicaSet "nginx-demo-5754944d6c" has successfully progressed.
    reason: NewReplicaSetAvailable
    status: "True"
    type: Progressing
  observedGeneration: 1
  readyReplicas: 1
  replicas: 1
  updatedReplicas: 1
    """
)


service_response = yaml.safe_load(
    """
apiVersion: v1
kind: Service
metadata:
  creationTimestamp: "2019-11-11T12:01:05Z"
  name: nginx-demo
  namespace: secondary
  resourceVersion: "8080020"
  selfLink: /api/v1/namespaces/secondary/services/nginx-demo
  uid: e2b789b0-19a1-493d-9f23-3f2a63fade52
spec:
  clusterIP: 10.100.78.172
  externalTrafficPolicy: Cluster
  ports:
  - nodePort: 32566
    port: 80
    protocol: TCP
    targetPort: 80
  selector:
    app: nginx
  sessionAffinity: None
  type: NodePort
status:
  loadBalancer: {}
    """
)

configmap_response = yaml.safe_load(
    """
apiVersion: v1
data:
  nginx_config: "myconfig"
kind: ConfigMap
metadata:
  annotations: {}
  creationTimestamp: "2020-07-21T13:57:03Z"
  managedFields: []
  name: nginx-demo
  namespace: secondary
  resourceVersion: "5073306"
  selfLink: /api/v1/namespaces/secondary/configmaps/nginx-demo
  uid: e851306b-4581-48f3-808d-1d18c9038309
    """
)

initial_last_observed_manifest_deployment = yaml.safe_load(
    """---
apiVersion: apps/v1
kind: Deployment
metadata:
  name: nginx-demo
  namespace: secondary
spec:
  replicas: 1
  selector:
    matchLabels:
      app: nginx
  template:
    metadata:
      labels:
        app: nginx
    spec:
      containers:
      - name: nginx
        image: nginx:1.7.9
        ports:
        - containerPort: 80
        - observer_schema_list_current_length: 1
      - observer_schema_list_current_length: 1
    """
)

initial_last_observed_manifest_service = yaml.safe_load(
    """
apiVersion: v1
kind: Service
metadata:
  name: nginx-demo
  namespace: secondary
spec:
  type: NodePort
  selector:
    app: nginx
  ports:
  - port: 80
    targetPort: 80
  - observer_schema_list_current_length: 1
    """
)

initial_last_observed_manifest_configmap = yaml.safe_load(
    """
apiVersion: v1
kind: ConfigMap
metadata:
  name: nginx-demo
  namespace: secondary
  """
)

initial_last_observed_manifest = [
    initial_last_observed_manifest_deployment,
    initial_last_observed_manifest_service,
    initial_last_observed_manifest_configmap,
]
