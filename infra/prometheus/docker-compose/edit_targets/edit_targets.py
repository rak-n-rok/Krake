import json
import os
from http import HTTPStatus

from flask import Flask, request, jsonify
from jsonschema import validate, ValidationError

app = Flask(__name__)


ABSPATH = os.path.dirname(os.path.abspath(__file__))


REQUEST_SCHEMA_ADD = {
  "definitions": {},
  "$schema": "http://json-schema.org/draft-07/schema#",
  "type": "object",
  "required": [
    "target",
    "node",
    "node_name"
  ],
  "properties": {
    "target": {
      "type": "string",
    },
    "node": {
      "type": "string",
      "enum": ["Krake", "Kubernetes", "OpenStack"]
    },
    "node_name": {
      "type": "string",
    }
  }
}

REQUEST_SCHEMA_REMOVE = {
  "definitions": {},
  "$schema": "http://json-schema.org/draft-07/schema#",
  "type": "object",
  "required": [
    "node_name"
  ],
  "properties": {
    "target": {
      "type": "string",
    },
    "node": {
      "type": "string",
      "enum": ["Krake", "Kubernetes", "OpenStack"]
    },
    "node_name": {
      "type": "string",
    }
  }
}


def edit_target(req, kind, remove=False):
    """
    Edits prometheus target directory

    Args:
        req (dict): requests body
        kind (str): target kind
        remove (bool): True removes target file. Defaults to False.

    """
    if kind not in ('krake_vm', 'openstack', 'k8s_cluster', 'app'):
        raise NotImplementedError

    path = os.path.join(ABSPATH, 'krake/targets/' + kind)

    filename = os.path.join(path, '.'.join((req['node_name'], 'json')))
    if remove:
        if os.path.exists(filename):
            os.remove(filename)
    else:
        data = [
            {
                "targets": [
                    req['target']
                ],
                "labels":
                    {
                        "node": req['node'],
                        "node_name": req['node_name']
                    }
            }
        ]
        with open(filename, 'w') as outfile:
            json.dump(data, outfile, indent=4)


@app.route('/<kind>', methods=['POST'])
def target_add(kind):
    """
    Handler for adding prometheus targets.
    """
    req = request.get_json()
    try:
        validate(req, REQUEST_SCHEMA_ADD)
    except ValidationError as e:
        return jsonify({'error': e.message}), HTTPStatus.BAD_REQUEST

    edit_target(req, kind)

    return '', HTTPStatus.OK


@app.route('/<kind>', methods=['DELETE'])
def target_remove(kind):
    """
    Handler for removing prometheus targets.
    """
    req = request.get_json()
    try:
        validate(req, REQUEST_SCHEMA_REMOVE)
    except ValidationError as e:
        return jsonify({'error': e.message}), HTTPStatus.BAD_REQUEST

    edit_target(req, kind, remove=True)

    return '', HTTPStatus.OK


if __name__ == '__main__':

    app.run(host='0.0.0.0', port=8080)
