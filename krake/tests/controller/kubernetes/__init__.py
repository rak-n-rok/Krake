import yaml
from textwrap import dedent
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

secret_manifest = yaml.safe_load(
    """---
apiVersion: v1
kind: Secret
metadata:
  name: nginx-demo
  namespace: secondary
data:
  nginx_config: "myconfig"
"""
)

nginx_manifest = [deployment_manifest, service_manifest, secret_manifest]

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

custom_secret_observer_schema = yaml.safe_load(
    """---
apiVersion: v1
kind: Secret
metadata:
  name: nginx-demo
  namespace: null
"""
)

custom_observer_schema = [
    custom_deployment_observer_schema,
    custom_service_observer_schema,
    custom_secret_observer_schema,
]

# To be used to initialize status.mangled_observer_schema when the controller loop is
# not called in the test.
mangled_deployment_observer_schema = deepcopy(custom_deployment_observer_schema)
mangled_service_observer_schema = deepcopy(custom_service_observer_schema)
mangled_secret_observer_schema = deepcopy(custom_secret_observer_schema)

mangled_observer_schema = [
    mangled_deployment_observer_schema,
    mangled_service_observer_schema,
    mangled_secret_observer_schema,
]


job_manifest = yaml.safe_load(
    """
apiVersion: batch/v1
kind: Job
metadata:
  name: pi
  namespace: secondary
spec:
  template:
    metadata:
      name: pi
    spec:
      containers:
        - name: pi
          image: perl
          command: ['perl', '-Mbignum=bpi', '-wle', 'print bpi(2000)']
      restartPolicy: Never
    """
)


job_response = yaml.safe_load(
    """
apiVersion: batch/v1
kind: Job
metadata:
  creationTimestamp: "2022-05-12T09:01:00Z"
  name: pi
  namespace: secondary
  resourceVersion: "5314"
  uid: d2a00bbb-0682-49d9-be86-fe100f504786
spec:
  backoffLimit: 6
  completions: 1
  parallelism: 1
  selector:
    matchLabels:
      controller-uid: d2a00bbb-0682-49d9-be86-fe100f504786
  template:
    metadata:
      creationTimestamp: null
      labels:
        controller-uid: d2a00bbb-0682-49d9-be86-fe100f504786
        job-name: pi
      name: pi
    spec:
      containers:
      - command:
        - perl
        - -Mbignum=bpi
        - -wle
        - print bpi(2000)
        image: perl
        imagePullPolicy: Always
        name: pi
        resources: {}
        terminationMessagePath: /dev/termination-log
        terminationMessagePolicy: File
      dnsPolicy: ClusterFirst
      restartPolicy: Never
      schedulerName: default-scheduler
      securityContext: {}
      terminationGracePeriodSeconds: 30
status:
  completionTime: "2022-05-12T09:01:15Z"
  conditions:
  - lastProbeTime: "2022-05-12T09:01:15Z"
    lastTransitionTime: "2022-05-12T09:01:15Z"
    status: "True"
    type: Complete
  startTime: "2022-05-12T09:01:00Z"
  succeeded: 1
    """
)


initial_last_observed_manifest_job = yaml.safe_load(
    """
apiVersion: batch/v1
kind: Job
metadata:
  name: pi
  namespace: secondary
    """
)


pv_manifest = yaml.safe_load(
    """
kind: PersistentVolume
apiVersion: v1
metadata:
  name: pv
  labels:
    type: local
spec:
  capacity:
    storage: 10Gi
  accessModes:
    - ReadWriteOnce
  hostPath:
    path: '/somepath/data'
    """
)


pv_response = yaml.safe_load(
    """
apiVersion: v1
kind: PersistentVolume
metadata:
  creationTimestamp: "2022-05-30T12:51:39Z"
  finalizers:
  - kubernetes.io/pv-protection
  labels:
    type: local
  name: pv
  resourceVersion: "28264"
  uid: 9614f82f-7f9d-4676-8252-723731d259be
spec:
  accessModes:
  - ReadWriteOnce
  capacity:
    storage: 10Gi
  hostPath:
    path: /somepath/data01
    type: ""
  persistentVolumeReclaimPolicy: Retain
  volumeMode: Filesystem
status:
  phase: Available
    """
)


initial_last_observed_manifest_pv = yaml.safe_load(
    """
apiVersion: v1
kind: PersistentVolume
metadata:
  name: pv
    """
)


cluster_role_manifest = yaml.safe_load(
    """
kind: ClusterRole
apiVersion: rbac.authorization.k8s.io/v1
metadata:
  name: admin
rules:
- apiGroups: ["*"]
  resources: ["*"]
  verbs: ["*"]
    """
)


cluster_role_response = yaml.safe_load(
    """
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  creationTimestamp: "2022-06-01T12:45:37Z"
  name: admin
  resourceVersion: "126747"
  uid: 581ace3d-f2f4-406d-8b4b-c131715bcce5
rules:
- apiGroups:
  - '*'
  resources:
  - '*'
  verbs:
  - '*'
    """
)


initial_last_observed_manifest_cluster_role = yaml.safe_load(
    """
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: admin
    """
)


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

secret_response = yaml.safe_load(
    """
apiVersion: v1
data:
  nginx_config: "myconfig"
kind: Secret
metadata:
  annotations: {}
  creationTimestamp: "2021-10-18T13:38:04Z"
  managedFields: []
  name: nginx-demo
  namespace: secondary
  resourceVersion: "439"
  selfLink: /api/v1/namespaces/secondary/secrets/nginx-secret
  uid: 9a7ecc91-83a9-47ae-8fed-ea9321b6e626
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

initial_last_observed_manifest_secret = yaml.safe_load(
    """
apiVersion: v1
kind: Secret
metadata:
  name: nginx-demo
  namespace: secondary
  """
)

initial_last_observed_manifest = [
    initial_last_observed_manifest_deployment,
    initial_last_observed_manifest_service,
    initial_last_observed_manifest_secret,
]


def crontab_crd(namespaced=True):
    """Return the custom resource definition for the CRON resource.

    Args:
        namespaced (bool): if True, the returned definition will be namespaced, if
            False, it will not (set to "Cluster").

    Returns:
        dict[str, object]: the generated custom resource definition.

    """
    return deepcopy(
        {
            "api_version": "apiextensions.k8s.io/v1",
            "kind": "CustomResourceDefinition",
            "spec": {
                "group": "stable.example.com",
                "names": {"kind": "CronTab", "plural": "crontabs"},
                "scope": "Namespaced" if namespaced else "Cluster",
                "versions": [{"name": "v1", "served": "True", "storage": "True"}],
            },
        }
    )


def create_cron_resource(name="cron", minute=5, image="cron-image"):
    """Create a CronTab resource from parameters.

    Args:
        name (str): name of the resource
        minute (int): time set for the minutes in the CRON specifications.
        image (str): image used for the CRON specifications.

    Returns:
        dict[str, object]: the generated CronTab resource.

    """
    return next(
        yaml.safe_load_all(
            dedent(
                f"""
            ---
            apiVersion: stable.example.com/v1
            kind: CronTab
            metadata:
                name: {name}
                namespace: default
            spec:
                cronSpec: "* * * * {minute}"
                image: {image}
            """
            )
        )
    )
