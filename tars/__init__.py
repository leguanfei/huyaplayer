from .__util import util
from .__tars import TarsInputStream, TarsOutputStream
from .__packet import RequestPacket, ResponsePacket
from .exception import *

# 类型别名
tarscore = util
tarscore.struct = util.struct
tarscore.int8 = util.int8
tarscore.int16 = util.int16
tarscore.int32 = util.int32
tarscore.int64 = util.int64
tarscore.string = util.string
tarscore.bytes = util.bytes
tarscore.TarsInputStream = TarsInputStream
tarscore.TarsOutputStream = TarsOutputStream
