import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from tars import tarscore


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


@auto_decode_fields
class HuyaUserId(tarscore.struct):
    """虎牙用户ID结构"""
    __tars_class__ = "HUYA.UserId"

    def __init__(self):
        self.lUid: tarscore.int64 = 0
        self.sGuid: tarscore.string = ""
        self.sToken: tarscore.string = ""
        self.sHuYaUA: tarscore.string = ""
        self.sCookie: tarscore.string = ""
        self.iTokenType: tarscore.int32 = 0
        self.sDeviceId: tarscore.string = ""
        self.sQIMEI: tarscore.string = ""

    @staticmethod
    def writeTo(oos, value):
        oos.write(tarscore.int64, 0, value.lUid)
        oos.write(tarscore.string, 1, value.sGuid)
        oos.write(tarscore.string, 2, value.sToken)
        oos.write(tarscore.string, 3, value.sHuYaUA)
        oos.write(tarscore.string, 4, value.sCookie)
        oos.write(tarscore.int32, 5, value.iTokenType)
        oos.write(tarscore.string, 6, value.sDeviceId)
        oos.write(tarscore.string, 7, value.sQIMEI)

    @staticmethod
    def readFrom(ios):
        value = HuyaUserId()
        value.lUid = ios.read(tarscore.int64, 0, False)
        value.sGuid = ios.read(tarscore.string, 1, False)
        value.sToken = ios.read(tarscore.string, 2, False)
        value.sHuYaUA = ios.read(tarscore.string, 3, False)
        value.sCookie = ios.read(tarscore.string, 4, False)
        value.iTokenType = ios.read(tarscore.int32, 5, False)
        value.sDeviceId = ios.read(tarscore.string, 6, False)
        value.sQIMEI = ios.read(tarscore.string, 7, False)
        return value
