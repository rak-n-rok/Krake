from http import HTTPStatus

from flask import Flask
from prometheus_client import Gauge, start_http_server

PROMETHEUS_PORT = 9000

KRAKE_METRIC = Gauge('krake_metric', 'float or int - krake metric')
HEAT_DEMAND = Gauge('heat_demand', 'float or int - heat demand (kW)')
KRAKE_METRIC.set(0)
HEAT_DEMAND.set(0)


class MetricMiddleware(object):

    def __init__(self, application):
        self.app = application
        # Start http server in separate thread to expose metrics for consumption by
        # prometheus
        self.start_metrics_server()

    @staticmethod
    def start_metrics_server():
        start_http_server(PROMETHEUS_PORT)

    def __call__(self, environ, start_response):
        return self.app(environ, start_response)


app = Flask(__name__)
app.wsgi_app = MetricMiddleware(app.wsgi_app)


@app.route('/krake_metric/<float:value>', methods=['POST'])
@app.route('/krake_metric/<int:value>', methods=['POST'])
def update_krake_metric(value):
    """
    Handler for updating krake metric.
    """
    KRAKE_METRIC.set(value)
    return '', HTTPStatus.OK


@app.route('/heat_demand/<float:value>', methods=['POST'])
@app.route('/heat_demand/<int:value>', methods=['POST'])
def update_heat_demand(value):
    """
    Handler for updating heat demand.
    """
    HEAT_DEMAND.set(value)
    return '', HTTPStatus.OK


if __name__ == '__main__':

    app.run(host='0.0.0.0', port=8080)
