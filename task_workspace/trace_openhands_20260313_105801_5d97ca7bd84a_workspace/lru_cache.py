from collections import OrderedDict


class LRUCache:
    def __init__(self, maxsize):
        if maxsize <= 0:
            raise ValueError("maxsize must be greater than 0")
        self.maxsize = maxsize
        self.cache = OrderedDict()

    def get(self, key):
        if key in self.cache:
            # Move to end to show it was recently used
            self.cache.move_to_end(key)
            return self.cache[key]
        raise KeyError(key)

    def put(self, key, value):
        if key in self.cache:
            # Update existing key
            self.cache.move_to_end(key)
        elif len(self.cache) >= self.maxsize:
            # Remove least recently used item (first item)
            self.cache.popitem(last=False)
        
        self.cache[key] = value