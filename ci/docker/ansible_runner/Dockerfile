# Dockerfile for assembling the ansible images used in the ci pipeline

FROM python:3.12

RUN apt-get update && apt-get upgrade -y

# Pre-requisites: openstack, ansible and pytest
RUN apt-get update -y && apt-get install openssh-client rsync -y
COPY ./ansible/requirements.yml krake-ci/ansible/requirements.yml
COPY ./ansible/ansible_control_node_requirements.txt krake-ci/ansible/ansible_control_node_requirements.txt
RUN pip install -r krake-ci/ansible/ansible_control_node_requirements.txt

RUN chmod -v 700 krake-ci/ansible/
RUN ansible-galaxy install -r krake-ci/ansible/requirements.yml
