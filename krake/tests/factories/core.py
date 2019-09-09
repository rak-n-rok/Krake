import random

import pytz
from factory import Factory, SubFactory, List, lazy_attribute, fuzzy
from datetime import datetime

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
    MetricProviderType,
    MetricProviderConfig,
)


def fuzzy_name():
    return "-".join(fake.name().split()).lower()


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
    created = fuzzy.FuzzyDateTime(datetime.now(tz=pytz.utc))

    @lazy_attribute
    def modified(self):
        delta = fake.time_delta()
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
        return [fuzzy_name() for i in range(fake.pyint(1, 10))]

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

    @lazy_attribute
    def name(self):
        return fake.word()

    @lazy_attribute
    def metric(self):
        return fake.word()


class MetricSpecFactory(Factory):
    class Meta:
        model = MetricSpec

    min = 0
    max = 1

    @lazy_attribute
    def value(self):
        return random.random()

    @lazy_attribute
    def weight(self):
        return random.random()

    provider = SubFactory(MetricSpecProviderFactory)


class MetricFactory(Factory):
    class Meta:
        model = Metric

    metadata = SubFactory(MetadataFactory)
    spec = SubFactory(MetricSpecFactory)


class MetricProviderConfigFactory(Factory):
    class Meta:
        model = MetricProviderConfig

    @lazy_attribute
    def url(self):
        return fake.url()

    @lazy_attribute
    def metrics(self):
        return fake.words()


class MetricsProviderSpecFactory(Factory):
    class Meta:
        model = MetricsProviderSpec

    @lazy_attribute
    def type(self):
        return fake.random.choice(list(MetricProviderType.__members__.values()))

    config = SubFactory(MetricProviderConfigFactory)


class MetricsProviderFactory(Factory):
    class Meta:
        model = MetricsProvider

    metadata = SubFactory(MetadataFactory)
    spec = SubFactory(MetricsProviderSpecFactory)
