import yaml

nginx_manifest = list(
    yaml.safe_load_all(
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
---
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
)
