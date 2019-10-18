class SimpleWorker(object):
    """Simple controller worker which validates received resource UIDs against
    a set of expected UIDs.

    Args:
        expected (set[str]): Set of expected resource UIDs
        loop (asyncio.AbstractEventLoop): Event loop to be used

    """

    def __init__(self, expected, loop):
        self.expected = expected
        self.received = set()
        self.done = loop.create_future()

    async def resource_received(self, resource):
        if self.done.done():
            return

        try:
            assert resource.metadata.uid in self.expected
            self.received.add(resource.metadata.uid)

            if self.received == self.expected:
                self.done.set_result(None)

        except AssertionError as err:
            self.done.set_exception(err)
