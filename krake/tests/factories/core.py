from dataclasses import MISSING

import pytz
from factory import Factory, SubFactory, List, lazy_attribute, fuzzy, Maybe, Dict
from datetime import timedelta

from .fake import fake
from krake.data.core import (
    Metadata,
    Verb,
    RoleRule,
    Role,
    RoleBinding,
    Reason,
    ReasonCode,
    Metric,
    MetricSpec,
    MetricSpecProvider,
    MetricsProvider,
    MetricsProviderSpec,
    PrometheusSpec,
    StaticSpec,
    MetricRef,
)


def fuzzy_name():
    return "-".join(fake.name().split()).lower()


def fuzzy_dict(size=None):
    if size is None:
        size = fake.pyint(0, 3)
    return {fake.word(): fake.word() for _ in range(size)}


def fuzzy_sample(population, k=None):
    if k is None:
        k = fake.pyint(1, len(population))

    return fake.random.sample(population, k)


class MetadataFactory(Factory):
    class Meta:
        model = Metadata

    name = fuzzy.FuzzyAttribute(fuzzy_name)
    namespace = "testing"
    uid = fuzzy.FuzzyAttribute(fake.uuid4)
    labels = fuzzy.FuzzyAttribute(fuzzy_dict)
    deleted = None  # Not deleted by default

    @lazy_attribute
    def created(self):
        return fake.date_time(tzinfo=pytz.utc)

    @lazy_attribute
    def modified(self):
        delta = timedelta(seconds=fake.pyint(0, 86400))  # 86400 s == 1 day
        return self.created + delta


class RoleRuleFactory(Factory):
    class Meta:
        model = RoleRule

    class Params:
        api_resources = {
            "core": ["role", "rolebinding"],
            "kubernetes": [
                "applications",
                "applications/complete",
                "applications/status",
                "clusters",
                "clusters/status",
            ],
        }

    @lazy_attribute
    def api(self):
        return fake.random.choice(list(self.api_resources.keys()))

    @lazy_attribute
    def resources(self):
        return fuzzy_sample(self.api_resources[self.api])

    @lazy_attribute
    def namespaces(self):
        return [fuzzy_name() for _ in range(fake.pyint(1, 10))]

    @lazy_attribute
    def verbs(self):
        return fuzzy_sample(list(Verb.__members__.values()))


class RoleFactory(Factory):
    class Meta:
        model = Role

    metadata = SubFactory(MetadataFactory)
    rules = List([SubFactory(RoleRuleFactory) for _ in range(2)])


class RoleBindingFactory(Factory):
    class Meta:
        model = RoleBinding

    class Params:
        user_count = 5
        role_count = 2

    metadata = SubFactory(MetadataFactory)

    @lazy_attribute
    def users(self):
        return [fuzzy_name() for _ in range(self.user_count)]

    @lazy_attribute
    def roles(self):
        return [fuzzy_name() for _ in range(self.role_count)]


class ReasonFactory(Factory):
    class Meta:
        model = Reason

    message = fake.sentence()
    code = fuzzy.FuzzyChoice(list(ReasonCode.__members__.values()))


class MetricSpecProviderFactory(Factory):
    class Meta:
        model = MetricSpecProvider

    name = fuzzy.FuzzyAttribute(fake.word)
    metric = fuzzy.FuzzyAttribute(fake.word)


class MetricSpecFactory(Factory):
    class Meta:
        model = MetricSpec

    min = 0
    max = 1
    provider = SubFactory(MetricSpecProviderFactory)


class MetricFactory(Factory):
    class Meta:
        model = Metric

    metadata = SubFactory(MetadataFactory)
    spec = SubFactory(MetricSpecFactory)


class PrometheusSpecFactory(Factory):
    class Meta:
        model = PrometheusSpec

    url = fuzzy.FuzzyAttribute(fake.url)


class StaticSpecFactory(Factory):
    class Meta:
        model = StaticSpec

    metrics = Dict(
        {
            "static_metric_1": fuzzy.FuzzyFloat(0, 1),
            "static_metric_2": fuzzy.FuzzyFloat(0, 1),
        }
    )


class MetricsProviderSpecFactory(Factory):
    class Meta:
        model = MetricsProviderSpec

    class Params:
        @lazy_attribute
        def is_prometheus(self):
            return self.type == "prometheus"

        @lazy_attribute
        def is_static(self):
            return self.type == "static"

    prometheus = Maybe("is_prometheus", SubFactory(PrometheusSpecFactory), MISSING)
    static = Maybe("is_static", SubFactory(StaticSpecFactory), MISSING)

    @lazy_attribute
    def type(self):
        return fake.random.choice(list(MetricsProviderSpec.Schema._registry.keys()))

    @classmethod
    def _create(cls, model_class, *args, **kwargs):
        # Remove MISSING attributes
        for key in list(kwargs.keys()):
            if kwargs[key] is MISSING:
                del kwargs[key]

        return model_class(*args, **kwargs)


class MetricsProviderFactory(Factory):
    class Meta:
        model = MetricsProvider

    metadata = SubFactory(MetadataFactory)
    spec = SubFactory(MetricsProviderSpecFactory)


class MetricRefFactory(Factory):
    class Meta:
        model = MetricRef

    weight = fuzzy.FuzzyFloat(0, 1.0)
    name = fuzzy.FuzzyAttribute(fake.word)
