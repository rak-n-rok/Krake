# -*- coding: utf-8 -*-

EXTRA_VARIABLES = {
    'uwsgi_processes': 1,
    # TODO Should be removed if trusted CA certificate takes place
    # This will be done in: https://publicgitlab.cloudandheat.com/ragnarok/krake/issues/168
    'prometheus_skip_verify': True
}

OUTPUT_OPTIONS = {
    'extension': ''
}
