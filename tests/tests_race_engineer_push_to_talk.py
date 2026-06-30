# MIT License
#
# Copyright (c) [2026] [Ashwin Natarajan]
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in all
# copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.

# pylint: skip-file

from io import BytesIO
import unittest
import wave

from lib.race_engineer import PushToTalkAudioBuffer


class TestRaceEngineerPushToTalk(unittest.TestCase):
    def test_pcm16_chunks_stop_as_wav_clip(self):
        buffer = PushToTalkAudioBuffer()

        buffer.start(session_id="abc", audio_format="pcm16", sample_rate_hz=16000, channels=1)
        buffer.append(b"\x00\x00" * 20)
        buffer.append(b"\x01\x00" * 20)
        clip = buffer.stop()

        self.assertIsNotNone(clip)
        self.assertFalse(buffer.active)
        self.assertEqual(buffer.raw_audio_bytes, 0)
        self.assertEqual(clip.session_id, "abc")
        self.assertEqual(clip.audio_format, "wav")
        self.assertEqual(clip.chunk_count, 2)
        self.assertEqual(clip.raw_audio_bytes, 80)
        self.assertTrue(clip.audio.startswith(b"RIFF"))
        with wave.open(BytesIO(clip.audio), "rb") as wav_file:
            self.assertEqual(wav_file.getframerate(), 16000)
            self.assertEqual(wav_file.getnchannels(), 1)
            self.assertEqual(wav_file.getsampwidth(), 2)
            self.assertEqual(wav_file.getnframes(), 40)

    def test_wav_format_keeps_audio_bytes_unchanged(self):
        buffer = PushToTalkAudioBuffer()

        buffer.start(audio_format="wav", content_type="audio/wav")
        buffer.append(b"RIFFfake")
        clip = buffer.stop()

        self.assertEqual(clip.audio, b"RIFFfake")
        self.assertEqual(clip.audio_format, "wav")
        self.assertEqual(clip.content_type, "audio/wav")

    def test_stop_without_audio_returns_none(self):
        buffer = PushToTalkAudioBuffer()

        buffer.start()

        self.assertIsNone(buffer.stop())
        self.assertFalse(buffer.active)

    def test_append_without_start_raises(self):
        buffer = PushToTalkAudioBuffer()

        with self.assertRaises(RuntimeError):
            buffer.append(b"audio")

    def test_buffer_limit_cancels_recording(self):
        buffer = PushToTalkAudioBuffer(max_audio_bytes=4)
        buffer.start()

        with self.assertRaises(ValueError):
            buffer.append(b"12345")

        self.assertFalse(buffer.active)
        self.assertEqual(buffer.raw_audio_bytes, 0)


if __name__ == "__main__":
    unittest.main()
