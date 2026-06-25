import pytest

from app.config.settings import Settings
from app.llm.opensdk_provider import OpenSDKLLMProvider


class FakeSDKClient:
    def __init__(self):
        self.close_calls = 0

    async def close(self):
        self.close_calls += 1


@pytest.mark.asyncio
async def test_opensdk_provider_does_not_close_external_client_by_default():
    sdk_client = FakeSDKClient()
    provider = OpenSDKLLMProvider(Settings(), client=sdk_client)

    await provider.close()

    assert sdk_client.close_calls == 0


@pytest.mark.asyncio
async def test_opensdk_provider_closes_explicitly_transferred_client():
    sdk_client = FakeSDKClient()
    provider = OpenSDKLLMProvider(Settings(), client=sdk_client, owns_client=True)

    await provider.close()
    await provider.close()

    assert sdk_client.close_calls == 1
