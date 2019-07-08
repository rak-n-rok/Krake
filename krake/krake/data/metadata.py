from .serializable import Serializable


class Metadata(Serializable):
    name: str
    namespace: str
    user: str
    uid: str
