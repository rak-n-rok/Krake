import pytz
from factory import Factory, SubFactory, List, lazy_attribute, fuzzy
from datetime import datetime

from .fake import fake
from krake.data.core import (
    NamespacedMetadata,
    CoreMetadata,
    Verb,
    RoleRule,
    RoleStatus,
    Role,
    RoleBinding,
    RoleBindingStatus,
)


def fuzzy_name():
    return "-".join(fake.name().split()).lower()


def fuzzy_sample(population, k=None):
    if k is None:
        k = fake.pyint(1, len(population))

    return fake.random.sample(population, k)


class NamespacedMetadataFactory(Factory):
    class Meta:
        model = NamespacedMetadata

    name = fuzzy.FuzzyAttribute(fuzzy_name)
    namespace = "testing"
    uid = fuzzy.FuzzyAttribute(fake.uuid4)
    user = fuzzy.FuzzyAttribute(fuzzy_name)


class SystemMetadataFactory(Factory):
    class Meta:
        model = CoreMetadata

    name = fuzzy.FuzzyAttribute(fuzzy_name)
    uid = fuzzy.FuzzyAttribute(fake.uuid4)


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


class RoleStatusFactory(Factory):
    class Meta:
        model = RoleStatus

    created = fuzzy.FuzzyDateTime(datetime.now(tz=pytz.utc))

    @lazy_attribute
    def modified(self):
        delta = fake.time_delta()
        return self.created + delta


class RoleFactory(Factory):
    class Meta:
        model = Role

    metadata = SubFactory(SystemMetadataFactory)
    rules = List([SubFactory(RoleRuleFactory) for _ in range(2)])
    status = SubFactory(RoleStatusFactory)


class RoleBindingStatusFactory(Factory):
    class Meta:
        model = RoleBindingStatus

    created = fuzzy.FuzzyDateTime(datetime.now(tz=pytz.utc))

    @lazy_attribute
    def modified(self):
        delta = fake.time_delta()
        return self.created + delta


class RoleBindingFactory(Factory):
    class Meta:
        model = RoleBinding

    class Params:
        user_count = 5
        role_count = 2

    metadata = SubFactory(SystemMetadataFactory)
    status = SubFactory(RoleBindingStatusFactory)

    @lazy_attribute
    def users(self):
        return [fuzzy_name() for _ in range(self.user_count)]

    @lazy_attribute
    def roles(self):
        return [fuzzy_name() for _ in range(self.role_count)]
