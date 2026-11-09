class Middleware:
    def __init__(self, cls, **options):
        self.cls = cls
        self.options = options

    def __iter__(self):
        as_tuple = (self.cls, self.options)
        return iter(as_tuple)
