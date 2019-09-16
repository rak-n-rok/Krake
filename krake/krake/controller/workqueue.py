from asyncio import Queue


class WorkQueue(object):
    def __init__(self, maxsize=0, loop=None):
        self.dirty = dict()
        self.processing = set()
        self.queue = Queue(maxsize=maxsize, loop=loop)

    async def put(self, key, item):
        if key not in self.processing:
            await self.queue.put(key)
        self.dirty[key] = item

    async def get(self):
        key = await self.queue.get()
        item = self.dirty.pop(key)
        self.processing.add(key)
        return key, item

    async def done(self, key):
        self.processing.discard(key)

        if key in self.dirty:
            await self.queue.put(key)

    def empty(self):
        return len(self.dirty) == 0

    def full(self):
        return self.queue.full()

    def size(self):
        return len(self.dirty)
