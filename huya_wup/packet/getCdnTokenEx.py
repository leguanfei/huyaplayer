import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from tars import tarscore
from huya_wup.wup_struct.UserId import HuyaUserId


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
class HuyaGetCdnTokenExReq(tarscore.struct):
    """获取CDN Token请求"""
    __tars_class__ = "HUYA.GetCdnTokenExReq"

    def __init__(self):
        self.sFlvUrl: tarscore.string = ""
        self.sStreamName: tarscore.string = ""
        self.iLoopTime: tarscore.int32 = 0
        self.tId: HuyaUserId = HuyaUserId()
        self.iAppId: tarscore.int32 = 66

    @staticmethod
    def writeTo(oos, value):
        oos.write(tarscore.string, 0, value.sFlvUrl)
        oos.write(tarscore.string, 1, value.sStreamName)
        oos.write(tarscore.int32, 2, value.iLoopTime)
        oos.write(HuyaUserId, 3, value.tId)
        oos.write(tarscore.int32, 4, value.iAppId)

    @staticmethod
    def readFrom(ios):
        value = HuyaGetCdnTokenExReq()
        value.sFlvUrl = ios.read(tarscore.string, 0, False)
        value.sStreamName = ios.read(tarscore.string, 1, False)
        value.iLoopTime = ios.read(tarscore.int32, 2, False)
        value.tId = ios.read(HuyaUserId, 3, False)
        value.iAppId = ios.read(tarscore.int32, 4, False)
        return value


@auto_decode_fields
class HuyaGetCdnTokenExRsp(tarscore.struct):
    """获取CDN Token响应"""
    __tars_class__ = "HUYA.GetCdnTokenExRsp"

    def __init__(self):
        self.sFlvToken: tarscore.string = ""
        self.iExpireTime: tarscore.int64 = 0

    @staticmethod
    def writeTo(oos, value):
        oos.write(tarscore.string, 0, value.sFlvToken)
        oos.write(tarscore.int64, 1, value.iExpireTime)

    @staticmethod
    def readFrom(ios):
        value = HuyaGetCdnTokenExRsp()
        value.sFlvToken = ios.read(tarscore.string, 0, False)
        value.iExpireTime = ios.read(tarscore.int64, 1, False)
        return value
