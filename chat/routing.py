from django.urls import re_path


def get_websocket_urlpatterns():
    from . import consumers
    return [
        re_path(r'ws/chat/$', consumers.ChatConsumer.as_asgi()),
    ]


# Lazy: se evalúa solo cuando Django ya está inicializado
class _LazyPatterns(list):
    _loaded = False

    def _load(self):
        if not self._loaded:
            self.extend(get_websocket_urlpatterns())
            self._loaded = True

    def __iter__(self):
        self._load()
        return super().__iter__()

    def __len__(self):
        self._load()
        return super().__len__()

    def __getitem__(self, item):
        self._load()
        return super().__getitem__(item)

    def __add__(self, other):
        self._load()
        return list(self) + list(other)

    def __radd__(self, other):
        self._load()
        return list(other) + list(self)


websocket_urlpatterns = _LazyPatterns()
