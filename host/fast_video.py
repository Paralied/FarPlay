"""Low-delay software H.264 for the pinned aiortc 1.15 encoder interface.

aiortc owns RTP/RTCP and bitrate adaptation. Only its H.264 codec creation
uses our speed preset; other encoders are unchanged. No hardware encoder
is assumed to exist on the user's PC.
"""
import fractions
import av
import aiortc.rtcrtpsender as sender_module
from aiortc.codecs import get_encoder
from aiortc.codecs.h264 import H264Encoder

class FastH264Encoder(H264Encoder):
    def _encode_frame(self, frame, force_keyframe):
        if self.codec and (frame.width != self.codec.width or frame.height != self.codec.height
                or abs(self.target_bitrate-self.codec.bit_rate)/self.codec.bit_rate > .1):
            self.codec = None
        if self.codec is None:
            self.codec = av.CodecContext.create('libx264','w')
            self.codec.width, self.codec.height = frame.width, frame.height
            self.codec.bit_rate = self.target_bitrate
            self.codec.pix_fmt = 'yuv420p'
            self.codec.framerate = fractions.Fraction(30,1)
            self.codec.time_base = fractions.Fraction(1,90000)
            self.codec.thread_count = 2
            self.codec.gop_size = 60
            self.codec.max_b_frames = 0
            self.codec.profile = 'Baseline'
            self.codec.options = {'level':'31','preset':'ultrafast','tune':'zerolatency'}
        yield from super()._encode_frame(frame, force_keyframe)

def encoder_factory(codec):
    return FastH264Encoder() if codec.mimeType.lower() == 'video/h264' else get_encoder(codec)

def install():
    sender_module.get_encoder = encoder_factory
