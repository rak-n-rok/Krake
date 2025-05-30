# Krake Kubernetes Setup

To set up Krake on a Proof of Concept (PoC) system, you will need a Kubernetes cluster to serve as a backend for the components.
For more detailed usage guidelines, explanations, and examples, please refer to the user documentation.

## System requirements

This quickstart requires you to have the following software components installed on your workstation:

- Python > 3.8.x
- kubectl
- Minimum required Kubernetes cluster version 1.24 and higher, such as Minikube, AKS or GKE

### Preparations

Clone the Krake git repository to your workstation:

``` shell
git clone https://gitlab.com/rak-n-rok/krake.git
cd krake
```

### Installation

Prepare your Kubernetes environment based on some manifests:

``` shell
kubectl apply -f examples/manifests/namespace.yaml # Create namespace in k8s
kubectl apply -f examples/manifests/database/      # Create database components in k8s
kubectl apply -f examples/manifests/backend/       # Create backend components in k8s
kubectl apply -f examples/manifests/frontend/      # Create frontend components in k8s
```

### Setup

Using a virtual environment on your workstation to implement Python dependencies is the recommended approach for a implementation:

``` shell
python3 -m venv .env
source .env/bin/activate

pip install wheel setuptools pip --upgrade
pip install "cython<3.0.0" wheel
pip install "pyyaml==5.4.1" --no-build-isolation
pip install honcho prometheus_async

pip install --editable krakectl/
pip install --editable krake/
```

### Configuration

Bootstrapping and configuring Krake amd the database in Kubernetes:

``` shell
# using "kubectl get nodes -o jsonpath='{range .items[*]}{.status.addresses[?(@.type=="InternalIP")].address}{"\n"}{end}'"
# to find a valid endpoint and replace db-host
# using "kubectl get svc etcd-client" to find nodeport and replace db-port

./.env/bin/krake_bootstrap_db --db-host=172.30.154.217 --db-port=30071 bootstrapping/base_roles.yaml

krake_generate_config --allow-anonymous --static-authentication-enabled templates/config/api.yaml.template

# edit api.yaml
# etcd:
  # host: 172.30.154.217
  # port: 30071

krake_generate_config templates/config/krakectl.yaml.template

# using "kubectl get nodes -o jsonpath='{range .items[*]}{.status.addresses[?(@.type=="InternalIP")].address}{"\n"}{end}'"
# to find a valid endpoint and replace db-host
# using "kubectl get svc krake-api" to find nodeport from and replace db-port

# edit krakectl.yaml and repace api_url
# api_url: http://172.30.154.217:30446

# using "kubectl get nodes -o jsonpath='{range .items[*]}{.status.addresses[?(@.type=="InternalIP")].address}{"\n"}{end}'"
# to find a valid endpoint and replace db-host
# using "kubectl get svc etcd-client" to find nodeport and replace db-port
./.env/bin/krake_bootstrap_db --db-host=172.30.154.217 --db-port=32375 support/prometheus_metrics.yaml support/static_metrics.yaml

# prepare Krake Kubernetes direct access
mkdir -p cluster_certs/certs cluster_certs/config
cp $KUBECONFIG cluster_certs/config/
krakectl kube cluster register -k cluster_certs/config/openstack_kuberetes_admin.conf

krakectl kube cluster list
```

 > **Note**

 >  The `--allow-anonymous` and `--static-authentication-enabled` options set the Krake API with
minimal authentication and authorization protections. It should not be used in production deployment!

### Testing

Using Krake CLI to execute demo test cases on your Kubernetes cluster:

``` shell
for i in {1..3}; do
  echo
  echo "Iteration: " $i
  kubectl get pods
  sleep 4
  krakectl kube app create -f templates/applications/k8s/echo-demo.yaml echo-demo
  sleep 2
  krakectl kube app list
  krakectl kube cluster list
  sleep 2
  krakectl kube app get echo-demo
  sleep 2
  krakectl kube app delete echo-demo
  sleep 8
done
sleep 8
krakectl kube cluster list
krakectl kube app list
kubectl get pods
```

## Uninstall

To remove the Krake components from Kubernetes, the following steps must be completed:

``` shell
kubectl delete -f examples/manifests/frontend/        # Delete the frontend components
kubectl delete -f examples/manifests/backend/         # Delete the backend components
kubectl delete -f examples/manifests/database/        # Delete the database components
kubectl delete -f examples/manifests/namespace.yaml   # Delete the namespace
```
