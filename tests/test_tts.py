import asyncio
import tempfile
import unittest
from pathlib import Path

from config import AppConfig, config
from errors import TransientPipelineError
from tts import generate_tts_result


class FakeCommunicator:
    calls = 0

    def __init__(self, text, voice, rate, volume):
        type(self).calls += 1

    async def stream(self):
        yield {"type": "audio", "data": b"fake-mp3"}
        yield {"type": "WordBoundary", "text": "测试", "offset": 2_000_000, "duration": 5_000_000}


class FailingCommunicator:
    def __init__(self, text, voice, rate, volume):
        pass

    async def stream(self):
        raise ConnectionError("temporary TTS network failure")
        yield


class DeterministicFailingCommunicator:
    calls = 0

    def __init__(self, text, voice, rate, volume):
        type(self).calls += 1

    async def stream(self):
        raise ValueError("invalid voice configuration")
        yield


class ClientConnectorError(Exception):
    pass


class ConnectorFailingCommunicator:
    def __init__(self, text, voice, rate, volume):
        pass

    async def stream(self):
        raise ClientConnectorError("DNS lookup failed")
        yield


class TimestampedTTSTests(unittest.TestCase):
    def _bind_config(self, root):
        path = Path(root) / "config.yaml"
        path.write_text(
            f'base_dir: "{str(root).replace(chr(92), chr(92) * 2)}"\nvideo_encoder: "libx264"\n',
            encoding="utf-8",
        )
        config.bind(AppConfig.from_file(str(path), environ={}))

    def test_streams_audio_and_normalizes_word_boundaries_to_seconds(self):
        with tempfile.TemporaryDirectory() as directory:
            self._bind_config(directory)
            output = Path(directory) / "speech.mp3"
            result = asyncio.run(generate_tts_result(
                "测试", str(output), voice="voice", cache_dir=None,
                communicator_factory=FakeCommunicator,
                duration_reader=lambda _: 1.0,
            ))
            self.assertEqual(output.read_bytes(), b"fake-mp3")
            self.assertEqual(result.boundaries[0].start, 0.2)
            self.assertEqual(result.boundaries[0].end, 0.7)

    def test_second_identical_request_uses_cache_without_network(self):
        with tempfile.TemporaryDirectory() as directory:
            self._bind_config(directory)
            FakeCommunicator.calls = 0
            cache = Path(directory) / "cache"
            first = Path(directory) / "first.mp3"
            second = Path(directory) / "second.mp3"
            asyncio.run(generate_tts_result(
                "缓存测试", str(first), voice="voice", cache_dir=str(cache),
                communicator_factory=FakeCommunicator, duration_reader=lambda _: 1.0,
            ))
            result = asyncio.run(generate_tts_result(
                "缓存测试", str(second), voice="voice", cache_dir=str(cache),
                communicator_factory=FakeCommunicator, duration_reader=lambda _: 1.0,
            ))
            self.assertEqual(FakeCommunicator.calls, 1)
            self.assertTrue(result.cache_hit)
            self.assertEqual(second.read_bytes(), b"fake-mp3")

    def test_exhausted_network_failure_remains_transient_for_batch_retry(self):
        with tempfile.TemporaryDirectory() as directory:
            self._bind_config(directory)
            with self.assertRaises(TransientPipelineError):
                asyncio.run(generate_tts_result(
                    "网络失败", str(Path(directory) / "speech.mp3"),
                    voice="voice", max_retries=1,
                    communicator_factory=FailingCommunicator,
                    duration_reader=lambda _: 1.0,
                ))

    def test_deterministic_tts_failure_is_not_retried_or_reclassified(self):
        with tempfile.TemporaryDirectory() as directory:
            self._bind_config(directory)
            DeterministicFailingCommunicator.calls = 0
            with self.assertRaisesRegex(ValueError, "invalid voice"):
                asyncio.run(generate_tts_result(
                    "配置失败", str(Path(directory) / "speech.mp3"),
                    voice="voice", max_retries=3,
                    communicator_factory=DeterministicFailingCommunicator,
                    duration_reader=lambda _: 1.0,
                ))
            self.assertEqual(DeterministicFailingCommunicator.calls, 1)

    def test_aiohttp_connector_style_failure_remains_transient(self):
        with tempfile.TemporaryDirectory() as directory:
            self._bind_config(directory)
            with self.assertRaises(TransientPipelineError):
                asyncio.run(generate_tts_result(
                    "连接失败", str(Path(directory) / "speech.mp3"),
                    voice="voice", max_retries=1,
                    communicator_factory=ConnectorFailingCommunicator,
                    duration_reader=lambda _: 1.0,
                ))


if __name__ == "__main__":
    unittest.main()
