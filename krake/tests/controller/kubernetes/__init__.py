import yaml
from krake.data.config import HooksConfiguration

nginx_manifest = list(
    yaml.safe_load_all(
        """---
apiVersion: extensions/v1beta1
kind: Deployment
metadata:
  name: nginx-demo
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
---
apiVersion: v1
kind: Service
metadata:
  name: nginx-demo
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
)


hooks_config = HooksConfiguration.deserialize(
    {
        "complete": {
            "ca_dest": "/etc/krake_ca/ca.pem",
            "env_token": "KRAKE_TOKEN",
            "env_complete": "KRAKE_COMPLETE_URL",
        }
    }
)
