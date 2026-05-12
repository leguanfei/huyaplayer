STANDARD_CHARSET = "UTF-8"


def auto_decode_fields(cls):
    """装饰器：自动为类添加 as_dict 方法"""
    original_init = cls.__init__

    def new_init(self, *args, **kwargs):
        original_init(self, *args, **kwargs)

    def as_dict(self):
        return {k: v for k, v in self.__dict__.items() if not k.startswith('_')}

    cls.__init__ = new_init
    cls.as_dict = as_dict
    return cls
